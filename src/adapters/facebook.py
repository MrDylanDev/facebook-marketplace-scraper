"""Facebook Marketplace adapter (Unit 4 slice).

Opt-in Playwright module from design #28 + spec #27
(facebook-playwright capability):

- Live path (opt-in): Playwright + ``storage_state`` round-trip
  (``auth_state.json``, never committed — see ``.gitignore``), stealth
  context when ``playwright-stealth`` is installed, gentle scrolling with
  ``N`` clamped to ``[1, MAX_LIMIT]``, login-wall/checkpoint abort, and
  exponential backoff + jitter on transient navigation errors.
- Fixture path (default in CI): :class:`FixtureLoader` serves recorded
  listings from ``tests/fixtures/fb_listings.json`` whenever
  ``FB_FIXTURE=1`` or no ``auth_state.json`` exists — CI never touches
  live Facebook.

Playwright is an optional ``facebook`` extra and is imported lazily
inside the live path only, so the fixture fallback (and this module's
import) works without it installed.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.models.listing import Listing

AUTH_STATE_PATH = "auth_state.json"
FIXTURE_ENV_VAR = "FB_FIXTURE"
FIXTURE_PATH_ENV_VAR = "FB_FIXTURE_PATH"
DEFAULT_LIMIT = 20
MAX_LIMIT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_SCROLL_PAUSE = 1.0
RESULTS_PER_SCROLL = 8
MARKETPLACE_SEARCH_URL = "https://www.facebook.com/marketplace/search/?query={query}"

_CHECKPOINT_PATTERNS = (
    "log in to continue",
    "log into facebook",
    "inicia sesión",
    "checkpoint",
    "verify your account",
    "confirma tu identidad",
)


class FacebookCheckpointError(RuntimeError):
    """Raised when Facebook shows a login wall / checkpoint (abort run)."""


def is_checkpoint(page_text: str) -> bool:
    """True when ``page_text`` looks like a login wall or checkpoint."""
    lowered = page_text.lower()
    return any(pattern in lowered for pattern in _CHECKPOINT_PATTERNS)


def raise_if_checkpoint(page_text: str) -> None:
    """Abort the run when ``page_text`` signals a login wall/checkpoint."""
    if is_checkpoint(page_text):
        raise FacebookCheckpointError(
            "Facebook login wall / checkpoint detected — aborting live run. "
            "Re-authenticate locally to refresh auth_state.json, or use "
            "FB_FIXTURE=1 for the recorded fixture."
        )


def clamp_limit(limit: int) -> int:
    """Clamp ``limit`` to the gentle range; ``<= 0`` means no results."""
    if limit <= 0:
        return 0
    return min(limit, MAX_LIMIT)


def run_with_backoff[T](
    fn: Callable[[], T],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base: float = DEFAULT_BACKOFF_BASE,
) -> T:
    """Run ``fn`` with exponential backoff + jitter on transient errors.

    Checkpoints are fatal (re-raised immediately, never retried).
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except FacebookCheckpointError:
            raise
        except Exception as exc:  # noqa: BLE001 — transient browser/net errors
            last_error = exc
            if attempt < max_retries:
                delay = base * (2**attempt) + random.uniform(0, base)
                if delay > 0:
                    time.sleep(delay)
    raise last_error  # type: ignore[misc]


def _parse_price_text(raw: Any) -> Decimal | None:
    """Parse human price text (``$ 85.000`` / ``$95,000`` / ``95000``)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.,-]", "", text)
    if not re.search(r"\d", cleaned):
        return None
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        if re.search(r",\d{2}$", cleaned):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            cleaned = cleaned.replace(".", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _default_fixture_path() -> str:
    return str(
        Path(__file__).resolve().parent.parent.parent
        / "tests"
        / "fixtures"
        / "fb_listings.json"
    )


class FixtureLoader:
    """Serve recorded Facebook listings (CI-safe, no browser, no network)."""

    def __init__(self, fixture_path: str | None = None) -> None:
        env_path = os.environ.get(FIXTURE_PATH_ENV_VAR)
        self.fixture_path = fixture_path or env_path or _default_fixture_path()

    def load(self) -> list[Listing]:
        """Load all recorded listings from the fixture file."""
        raw = json.loads(Path(self.fixture_path).read_text(encoding="utf-8"))
        entries = raw.get("listings", []) if isinstance(raw, dict) else raw
        return [Listing(**entry) for entry in entries]

    def get_item(self, item_id: str) -> Listing | None:
        """Return the recorded listing with ``item_id``, if present."""
        for listing in self.load():
            if listing.id == item_id:
                return listing
        return None


def parse_card(raw: dict[str, Any]) -> Listing:
    """Map one scraped DOM card dict to the shared :class:`Listing` schema."""
    price = _parse_price_text(raw.get("price_text", raw.get("price")))
    return Listing(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        price=price,
        currency=raw.get("currency") or ("ARS" if price is not None else None),
        url=str(raw.get("url", "")),
        image_url=raw.get("image_url"),
        seller=raw.get("seller"),
        location=raw.get("location"),
    )


def _listing_from_json_node(node: dict[str, Any]) -> Listing | None:
    node_id = node.get("id")
    title = node.get("marketplace_listing_title", node.get("title"))
    if not node_id or not title:
        return None
    price_block = node.get("listing_price") or {}
    amount = price_block.get("amount", node.get("price"))
    photo = node.get("primary_listing_photo") or {}
    image = (photo.get("image") or {}).get("uri", node.get("image_url"))
    location_block = node.get("location") or {}
    geo = location_block.get("reverse_geocode") or {}
    location = geo.get("city", node.get("location"))
    if isinstance(location, dict):
        location = geo.get("city") or geo.get("state")
    return Listing(
        id=str(node_id),
        title=str(title),
        price=_parse_price_text(amount),
        currency=price_block.get("currency", node.get("currency")),
        url=str(
            node.get("url") or f"https://www.facebook.com/marketplace/item/{node_id}"
        ),
        image_url=image,
        seller=node.get("seller"),
        location=location,
    )


def parse_embedded_json(payload: dict[str, Any]) -> list[Listing]:
    """Map embedded page JSON (Relay-style) to :class:`Listing` items.

    Walks the payload for ``results`` lists and converts each node;
    unknown shapes are skipped so selector renames degrade gracefully.
    """
    listings: list[Listing] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            results = node.get("results")
            if isinstance(results, list) and results and isinstance(results[0], dict):
                for entry in results:
                    listing = _listing_from_json_node(entry)
                    if listing is not None:
                        listings.append(listing)
                return
            listing = _listing_from_json_node(node)
            if listing is not None and "marketplace_listing_title" in node:
                listings.append(listing)
                return
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for entry in node:
                visit(entry)

    visit(payload)
    return listings


class FacebookAdapter:
    """Scrape Facebook Marketplace via Playwright, with fixture fallback.

    ``FB_FIXTURE=1`` or a missing ``auth_state.json`` selects the recorded
    fixture (CI-safe). Otherwise the live Playwright path runs with the
    ``storage_state`` session, gentle scroll limits, and checkpoint abort.
    """

    def __init__(
        self,
        auth_state: str = AUTH_STATE_PATH,
        fixture_path: str | None = None,
        use_fixture: bool = False,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        scroll_pause: float = DEFAULT_SCROLL_PAUSE,
        headless: bool = True,
    ) -> None:
        self.auth_state = auth_state
        self.fixture_path = fixture_path
        self.use_fixture = use_fixture
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.scroll_pause = scroll_pause
        self.headless = headless

    def _fixture_requested(self) -> bool:
        if self.use_fixture or os.environ.get(FIXTURE_ENV_VAR) == "1":
            return True
        return not os.path.exists(self.auth_state)

    def _loader(self) -> FixtureLoader:
        return FixtureLoader(self.fixture_path)

    def search(self, query: str, limit: int) -> Iterable[Listing]:
        """Yield up to ``limit`` listings (fixture or live, gently capped)."""
        capped = clamp_limit(limit)
        if capped == 0:
            return []
        if self._fixture_requested():
            return self._loader().load()[:capped]
        return self._live_search(query, capped)

    def get_item(self, item_id: str) -> Listing | None:
        """Fetch one listing by id (fixture lookup or live detail page)."""
        if self._fixture_requested():
            return self._loader().get_item(item_id)
        return self._live_detail(item_id)

    def close(self) -> None:
        """Release resources (fixture mode holds none; live uses contexts)."""

    def save_auth_state(self, path: str | None = None) -> str:
        """One-time manual login that persists ``storage_state`` for reuse.

        Opens a headed browser so the user logs in manually; the resulting
        session is written to ``path`` (default ``auth_state.json``).
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install the facebook extra: "
                "pip install 'facebook-marketplace-scraper[facebook]' "
                "&& playwright install chromium"
            ) from exc
        target = path or self.auth_state
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.facebook.com/marketplace/")
            input("Log in manually in the opened browser, then press Enter here... ")
            context.storage_state(path=target)
            browser.close()
        return target

    def _live_search(self, query: str, limit: int) -> list[Listing]:
        """Live Playwright scrape: stealth ctx → gentle scroll → parse."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed but a live Facebook run was "
                "requested (auth_state exists and FB_FIXTURE is unset). "
                "Install the facebook extra or set FB_FIXTURE=1."
            ) from exc

        def run() -> list[Listing]:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                try:
                    context = browser.new_context(storage_state=self.auth_state)
                except Exception:  # noqa: BLE001 — stored state may be stale; fall back to a fresh context
                    context = browser.new_context()
                try:
                    _apply_stealth(context)
                except Exception:  # noqa: BLE001, S110 — stealth is best-effort; silence is intentional
                    pass
                page = context.new_page()
                page.goto(
                    MARKETPLACE_SEARCH_URL.format(query=query),
                    wait_until="domcontentloaded",
                )
                raise_if_checkpoint(page.content())
                cards = self._gentle_scroll_collect(page, limit)
                return cards[:limit]
            # Unreachable: browser closed via context manager.

        return run_with_backoff(
            run, max_retries=self.max_retries, base=self.backoff_base
        )

    def _gentle_scroll_collect(self, page: Any, limit: int) -> list[Listing]:
        """Scroll gently (bounded passes + pauses) and parse DOM cards."""
        max_scrolls = max(1, -(-limit // RESULTS_PER_SCROLL))
        seen: dict[str, Listing] = {}
        for _ in range(max_scrolls):
            raise_if_checkpoint(page.content())
            for raw in _extract_cards(page):
                try:
                    listing = parse_card(raw)
                except Exception:  # noqa: BLE001, S112 — skip malformed cards
                    continue
                seen.setdefault(listing.id, listing)
                if len(seen) >= limit:
                    return list(seen.values())
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            if self.scroll_pause > 0:
                time.sleep(self.scroll_pause)
        return list(seen.values())

    def _live_detail(self, item_id: str) -> Listing | None:
        """Fetch one live item page; ``None`` when unavailable."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed but a live Facebook detail "
                "fetch was requested. Set FB_FIXTURE=1 for fixture mode."
            ) from exc

        def run() -> Listing | None:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                context = browser.new_context(storage_state=self.auth_state)
                page = context.new_page()
                page.goto(
                    f"https://www.facebook.com/marketplace/item/{item_id}",
                    wait_until="domcontentloaded",
                )
                raise_if_checkpoint(page.content())
                cards = _extract_cards(page)
                for raw in cards:
                    if str(raw.get("id")) == item_id:
                        return parse_card(raw)
                return None

        return run_with_backoff(
            run, max_retries=self.max_retries, base=self.backoff_base
        )


def _apply_stealth(context: Any) -> None:
    """Apply playwright-stealth evasions when the package is installed."""
    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        return
    stealth_sync(context)


def _extract_cards(page: Any) -> list[dict[str, Any]]:
    """Extract raw card dicts via selectors with embedded-JSON fallback."""
    try:
        anchors = page.query_selector_all("a[href*='/marketplace/item/']")
    except Exception:  # noqa: BLE001 — selector engine unavailable
        anchors = []
    cards: list[dict[str, Any]] = []
    for anchor in anchors:
        try:
            cards.append(_card_from_anchor(anchor))
        except Exception:  # noqa: BLE001, S112 — skip unparseable anchors
            continue
    if cards:
        return cards
    try:
        payload = page.evaluate(
            "() => { const el = document.getElementById('embedded-json');"
            " return el ? JSON.parse(el.textContent) : null; }"
        )
    except Exception:  # noqa: BLE001 — no embedded JSON available
        return []
    if not payload:
        return []
    return [listing.model_dump() for listing in parse_embedded_json(payload)]


def _card_from_anchor(anchor: Any) -> dict[str, Any]:
    href = anchor.get_attribute("href") or ""
    item_id = href.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    text = anchor.inner_text() or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    price_text = lines[1] if len(lines) > 1 else None
    image = anchor.query_selector("img")
    return {
        "id": item_id,
        "title": title,
        "price_text": price_text,
        "url": href if href.startswith("http") else f"https://www.facebook.com{href}",
        "image_url": image.get_attribute("src") if image else None,
        "seller": None,
        "location": lines[2] if len(lines) > 2 else None,
    }
