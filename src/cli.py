"""CLI (Unit 4: MercadoLibre + Facebook fixture fallback + --out export)."""

from __future__ import annotations

import argparse

TARGET_MERCADOLIBRE = "mercadolibre"

EXPORT_EXTENSIONS = (".csv", ".json", ".db", ".sqlite", ".sqlite3")


def normalize_target(raw: str) -> str:
    """Accept the ``mercado-libre`` alias for the ``mercadolibre`` target."""
    if raw.replace("-", "") == TARGET_MERCADOLIBRE:
        return TARGET_MERCADOLIBRE
    return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marketplace-scraper",
        description="Portfolio marketplace scraper.",
    )
    parser.add_argument("--query", default="", help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument(
        "--target",
        default="mercadolibre",
        help="Marketplace target: mercadolibre (or mercado-libre) | facebook (opt-in demo)",
    )
    parser.add_argument("--out", default="", help="Output path (CSV/SQLite/JSON)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = normalize_target(args.target)
    if target == TARGET_MERCADOLIBRE and args.query:
        return _run_mercadolibre_search(args.query, args.limit, args.out)
    if target == "facebook" and args.query:
        return _run_facebook_search(args.query, args.limit, args.out)
    print(f"target={target} query={args.query!r} limit={args.limit} out={args.out!r}")
    if target == "facebook":
        print("Facebook module: pass --query to search (fixture fallback in CI).")
    else:
        print("Scaffold only: pass --query to search MercadoLibre.")
    return 0


def _run_mercadolibre_search(query: str, limit: int, out: str = "") -> int:
    import httpx

    from src.adapters.mercado_libre import MercadoLibreAdapter

    adapter = MercadoLibreAdapter()
    try:
        results = list(adapter.search(query, limit))
    except httpx.HTTPError as exc:
        print(f"Search failed: {exc}")
        return 1
    finally:
        adapter.close()
    if out:
        return _export_results(results, out)
    if not results:
        print("No listings found.")
        return 0
    for listing in results:
        price = f"{listing.price} {listing.currency or ''}".strip()
        print(f"- [{listing.id}] {listing.title} | {price} | {listing.url}")
    return 0


def _run_facebook_search(query: str, limit: int, out: str = "") -> int:
    from src.adapters.facebook import FacebookAdapter

    adapter = FacebookAdapter()
    try:
        results = list(adapter.search(query, limit))
    except RuntimeError as exc:
        print(f"Facebook search unavailable: {exc}")
        return 1
    finally:
        adapter.close()
    if out:
        return _export_results(results, out)
    if not results:
        print("No listings found.")
        return 0
    for listing in results:
        price = f"{listing.price} {listing.currency or ''}".strip()
        print(f"- [{listing.id}] {listing.title} | {price} | {listing.url}")
    return 0


def _export_results(results: list, out: str) -> int:
    """Write search results to ``out`` (CSV/SQLite/JSON by extension)."""
    from src.exporters.csv_exporter import export_csv
    from src.exporters.json_exporter import export_json
    from src.exporters.sqlite_exporter import export_sqlite

    suffix = out.rsplit(".", 1)[-1].lower() if "." in out else ""
    if suffix == "csv":
        count = export_csv(results, out)
    elif suffix == "json":
        count = export_json(results, out)
    elif suffix in ("db", "sqlite", "sqlite3"):
        count = export_sqlite(results, out)
    else:
        print(
            f"Unsupported export format for {out!r} (use: {', '.join(EXPORT_EXTENSIONS)})"
        )
        return 2
    print(f"Exported {count} listings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
