"""Google Maps search agent (no API key required).

This scrapes the public Google Maps search results page and extracts the
place data that Google embeds in the page inside a JS variable called
``window.APP_INITIALIZATION_STATE``. Because it relies on the page's
internal data structure (which Google can change at any time) it is best
effort, not a stable API.

Usage (CLI):
    python google_maps_search.py "coffee near Times Square New York"
    python google_maps_search.py "pizza in Hanoi" --limit 5 --json

Usage (import):
    from google_maps_search import search_google_maps
    places = search_google_maps("coffee in Da Nang", limit=10)

Notes:
    * No official Google Maps API key is used. Scraping Google Maps may be
      against Google's Terms of Service -- use responsibly and at low volume.
    * Only the standard library + ``requests`` are required.
"""

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, asdict
from typing import Any, List, Optional

import requests

# A normal-looking desktop browser User-Agent. Google serves the data blob
# only to clients it believes are real browsers.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_SEARCH_URL = "https://www.google.com/maps/search/{query}?hl=en&gl=us"


@dataclass
class Place:
    """A single place returned from a Google Maps search."""

    name: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def maps_url(self) -> Optional[str]:
        """A shareable Google Maps link for this place's coordinates."""
        if self.latitude is None or self.longitude is None:
            return None
        return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"


def _get(value: Any, *path: int) -> Any:
    """Safely walk a nested list/dict by index/key, returning None on miss."""
    cur = value
    for key in path:
        try:
            cur = cur[key]
        except (IndexError, KeyError, TypeError):
            return None
    return cur


def _fetch_raw(query: str, timeout: int) -> str:
    """Fetch the Google Maps search page HTML for ``query``."""
    url = _SEARCH_URL.format(query=urllib.parse.quote(query))
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_init_state(html: str) -> Any:
    """Pull and JSON-decode the APP_INITIALIZATION_STATE array from the page."""
    match = re.search(
        r"window\.APP_INITIALIZATION_STATE\s*=\s*(\[.*?\]);",
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError(
            "Could not find APP_INITIALIZATION_STATE in the page. "
            "Google may have changed its layout or blocked the request."
        )
    return json.loads(match.group(1))


def _find_results_blob(init_state: Any) -> Any:
    """Locate the inner JSON string that holds the list of place results.

    Inside APP_INITIALIZATION_STATE there are several entries that are
    themselves JSON strings prefixed with the XSSI guard ``)]}'``. The one
    we want contains the search result list, so we scan all string entries
    and parse the first that looks like results.
    """
    candidates: List[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str) and node.startswith(")]}'"):
            candidates.append(node)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(init_state)

    for raw in candidates:
        try:
            parsed = json.loads(raw[raw.index("\n") + 1:]) if "\n" in raw else json.loads(raw[4:])
        except (ValueError, json.JSONDecodeError):
            continue
        # The results list lives at index [0][1] in the search blob.
        results = _get(parsed, 0, 1)
        if isinstance(results, list) and len(results) > 1:
            return results
    return None


def _parse_place(entry: Any) -> Optional[Place]:
    """Extract a Place from one raw result entry, or None if not a place."""
    detail = _get(entry, 14)
    if not isinstance(detail, list):
        return None

    rating = _get(detail, 4, 7)
    reviews = _get(detail, 4, 8)

    place = Place(
        name=_get(detail, 11),
        address=_get(detail, 39) or _get(detail, 18),
        category=_get(detail, 13, 0),
        rating=float(rating) if isinstance(rating, (int, float)) else None,
        reviews=int(reviews) if isinstance(reviews, (int, float)) else None,
        phone=_get(detail, 178, 0, 0) or _get(detail, 178, 0, 1),
        website=_get(detail, 7, 0),
        latitude=_get(detail, 9, 2),
        longitude=_get(detail, 9, 3),
    )
    # Skip empty rows (the first result entry is often a header/null).
    if not place.name:
        return None
    return place


def search_google_maps(
    query: str,
    limit: int = 20,
    timeout: int = 30,
) -> List[Place]:
    """Search Google Maps and return a list of :class:`Place` results.

    Args:
        query: Free-text search, e.g. ``"coffee near Times Square"``.
        limit: Maximum number of places to return.
        timeout: HTTP request timeout in seconds.

    Returns:
        A list of :class:`Place` objects (possibly empty).
    """
    html = _fetch_raw(query, timeout=timeout)
    init_state = _extract_init_state(html)
    results = _find_results_blob(init_state)
    if not results:
        return []

    places: List[Place] = []
    for entry in results:
        place = _parse_place(entry)
        if place is not None:
            places.append(place)
        if len(places) >= limit:
            break
    return places


def _format_human(places: List[Place]) -> str:
    if not places:
        return "No results found."
    lines = []
    for i, p in enumerate(places, 1):
        rating = f"{p.rating}★" if p.rating is not None else "no rating"
        reviews = f" ({p.reviews} reviews)" if p.reviews else ""
        lines.append(f"{i}. {p.name} — {rating}{reviews}")
        if p.category:
            lines.append(f"   {p.category}")
        if p.address:
            lines.append(f"   {p.address}")
        if p.phone:
            lines.append(f"   {p.phone}")
        if p.website:
            lines.append(f"   {p.website}")
        if p.maps_url:
            lines.append(f"   {p.maps_url}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search Google Maps without an API key."
    )
    parser.add_argument("query", help="What to search for, e.g. 'pizza in Hanoi'")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max results (default: 20)"
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output results as JSON"
    )
    args = parser.parse_args(argv)

    try:
        places = search_google_maps(
            args.query, limit=args.limit, timeout=args.timeout
        )
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = [{**asdict(p), "maps_url": p.maps_url} for p in places]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_format_human(places))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
