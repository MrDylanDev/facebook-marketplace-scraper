"""Streaming exporter tests (Unit 3 slice).

STRICT TDD: written BEFORE src/exporters/*.py.
Covers design #28 + spec #27 (listing-export capability):
- CSV / SQLite / JSON writers consume Iterable[Listing] in streaming fashion
- stdlib only (csv / sqlite3 / json), generator-safe (single pass, no len()/list())
- Decimal price preserved; None fields handled; empty input valid output

No live network, no Facebook.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from decimal import Decimal


def _full_listing(**overrides):
    from src.models.listing import Listing

    base = {
        "id": "MLA123",
        "title": "Bicicleta rodado 29",
        "price": Decimal("150000.00"),
        "currency": "ARS",
        "url": "https://articulo.mercadolibre.com.ar/MLA123",
        "image_url": "https://http2.mlstatic.com/MLA123.jpg",
        "seller": "seller1",
        "location": "Buenos Aires",
    }
    base.update(overrides)
    return Listing(**base)


def _minimal_listing():
    from src.models.listing import Listing

    return Listing(id="1", title="Bike", url="https://example.com/1")


# ---------------------------------------------------------------- CSV ---


def test_csv_writes_header_and_rows_round_trip(tmp_path):
    from src.exporters.csv_exporter import export_csv

    out = tmp_path / "out.csv"
    count = export_csv(
        [_full_listing(), _full_listing(id="MLA456", title="Casco")], out
    )

    assert count == 2
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["id"] == "MLA123"
    assert rows[0]["title"] == "Bicicleta rodado 29"
    assert rows[0]["currency"] == "ARS"
    assert rows[0]["url"].startswith("https://")
    assert rows[1]["id"] == "MLA456"


def test_csv_empty_iterable_writes_header_only(tmp_path):
    from src.exporters.csv_exporter import export_csv

    out = tmp_path / "out.csv"
    assert export_csv([], out) == 0
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 1  # header only
    assert rows[0][0] == "id"


def test_csv_quotes_commas_and_handles_none_price(tmp_path):
    from src.exporters.csv_exporter import export_csv

    out = tmp_path / "out.csv"
    listing = _full_listing(title='Bici, rodado "29"', price=None, seller=None)
    assert export_csv([listing], out) == 1
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["title"] == 'Bici, rodado "29"'
    assert rows[0]["price"] == ""
    assert rows[0]["seller"] == ""


def test_csv_consumes_one_shot_generator(tmp_path):
    """Streaming proof: a generator (no len, single pass) must work."""
    from src.exporters.csv_exporter import export_csv

    out = tmp_path / "out.csv"
    gen = (_full_listing(id=f"MLA{i}") for i in range(5))
    assert export_csv(gen, out) == 5
    with open(out, newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 5


# -------------------------------------------------------------- SQLite ---


def test_sqlite_creates_table_and_inserts_rows(tmp_path):
    from src.exporters.sqlite_exporter import export_sqlite

    out = tmp_path / "out.db"
    count = export_sqlite(
        [_full_listing(), _full_listing(id="MLA456", title="Casco")], out
    )

    assert count == 2
    conn = sqlite3.connect(out)
    try:
        rows = conn.execute(
            "SELECT id, title, currency, url FROM listings ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert rows[0][0] == "MLA123"
    assert rows[0][1] == "Bicicleta rodado 29"
    assert rows[0][2] == "ARS"
    assert rows[1][0] == "MLA456"


def test_sqlite_empty_iterable_creates_schema(tmp_path):
    from src.exporters.sqlite_exporter import export_sqlite

    out = tmp_path / "out.db"
    assert export_sqlite([], out) == 0
    conn = sqlite3.connect(out)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM listings").fetchone()
    finally:
        conn.close()
    assert count == 0


def test_sqlite_preserves_decimal_price_as_text(tmp_path):
    from src.exporters.sqlite_exporter import export_sqlite

    out = tmp_path / "out.db"
    export_sqlite([_full_listing(price=Decimal("150000.00"))], out)
    conn = sqlite3.connect(out)
    try:
        (stored,) = conn.execute("SELECT price FROM listings").fetchone()
    finally:
        conn.close()
    assert Decimal(str(stored)) == Decimal("150000.00")


def test_sqlite_consumes_one_shot_generator(tmp_path):
    """Streaming proof: a generator (no len, single pass) must work."""
    from src.exporters.sqlite_exporter import export_sqlite

    out = tmp_path / "out.db"
    gen = (_full_listing(id=f"MLA{i}") for i in range(4))
    assert export_sqlite(gen, out) == 4


# ---------------------------------------------------------------- JSON ---


def test_json_writes_valid_array_round_trip(tmp_path):
    from src.exporters.json_exporter import export_json

    out = tmp_path / "out.json"
    count = export_json(
        [_full_listing(), _full_listing(id="MLA456", title="Casco")], out
    )

    assert count == 2
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["id"] == "MLA123"
    assert data[0]["price"] == "150000.00"
    assert data[0]["currency"] == "ARS"
    assert data[1]["id"] == "MLA456"


def test_json_empty_iterable_writes_empty_array(tmp_path):
    from src.exporters.json_exporter import export_json

    out = tmp_path / "out.json"
    assert export_json([], out) == 0
    with open(out, encoding="utf-8") as fh:
        assert json.load(fh) == []


def test_json_consumes_one_shot_generator(tmp_path):
    """Streaming proof: a generator (no len, single pass) must work."""
    from src.exporters.json_exporter import export_json

    out = tmp_path / "out.json"
    gen = (_full_listing(id=f"MLA{i}") for i in range(3))
    assert export_json(gen, out) == 3
    with open(out, encoding="utf-8") as fh:
        assert len(json.load(fh)) == 3


def test_all_exporters_handle_minimal_listing(tmp_path):
    """Minimal Listing (only id/title/url) exports without errors."""
    import sqlite3 as _sqlite3

    from src.exporters.csv_exporter import export_csv
    from src.exporters.json_exporter import export_json
    from src.exporters.sqlite_exporter import export_sqlite

    assert export_csv([_minimal_listing()], tmp_path / "m.csv") == 1
    assert export_json([_minimal_listing()], tmp_path / "m.json") == 1
    assert export_sqlite([_minimal_listing()], tmp_path / "m.db") == 1

    with open(tmp_path / "m.json", encoding="utf-8") as fh:
        (row,) = json.load(fh)
    assert row["price"] is None
    conn = _sqlite3.connect(tmp_path / "m.db")
    try:
        (price,) = conn.execute("SELECT price FROM listings").fetchone()
    finally:
        conn.close()
    assert price is None
