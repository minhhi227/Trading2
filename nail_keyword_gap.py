"""Find the search keywords a nail salon does NOT rank for on Google Maps.

Given a target business name (e.g. "Queen Nail") and a location, this runs a
Google Maps search for each keyword in a list and reports:

  * MISSING  -> the business did not appear in the top results
               (good candidates to target with Google Ads)
  * FOUND    -> the business appeared, with its rank in the results

It builds on google_maps_search.py, so it needs no API key. Note that Google
blocks requests from many cloud/datacenter IPs (HTTP 403); run this from your
own machine / a residential connection for reliable results.

Usage:
    python nail_keyword_gap.py "Queen Nail" "Houston TX"
    python nail_keyword_gap.py "Queen Nail" "San Jose CA" --limit 20 --json
    python nail_keyword_gap.py "Queen Nail" "Houston TX" \
        --keywords "nail salon,gel nails,pedicure near me"

Caveats:
    * Google Maps organic ranking is location-personalised and changes over
      time; treat this as a directional gap analysis, not exact Ads data.
    * Maps presence != Google Ads keywords, but the keywords you are absent
      for are a sensible starting point for an Ads campaign.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

import requests

from google_maps_search import search_google_maps

# A reasonable default set of search terms people use to find nail salons.
DEFAULT_KEYWORDS: List[str] = [
    "nail salon",
    "nail salon near me",
    "nails near me",
    "manicure",
    "pedicure",
    "manicure and pedicure",
    "gel nails",
    "gel manicure",
    "acrylic nails",
    "dip powder nails",
    "nail art",
    "nail extensions",
    "full set nails",
    "french manicure",
    "spa pedicure",
    "kids manicure",
    "waxing",
    "eyelash extensions",
    "best nail salon",
    "cheap nail salon",
    "luxury nail salon",
    "walk in nail salon",
    "nail salon open now",
    "nail salon open sunday",
]


@dataclass
class KeywordResult:
    keyword: str
    found: bool
    rank: Optional[int] = None       # 1-based position if found
    competitors: Optional[List[str]] = None   # top names seen for context
    error: Optional[str] = None


def _name_matches(target: str, candidate: str) -> bool:
    """Loose match: case-insensitive substring either direction."""
    t = target.lower().strip()
    c = (candidate or "").lower().strip()
    return bool(c) and (t in c or c in t)


def analyze_keyword(
    business: str,
    keyword: str,
    location: str,
    limit: int,
    timeout: int,
) -> KeywordResult:
    query = f"{keyword} {location}".strip()
    try:
        places = search_google_maps(query, limit=limit, timeout=timeout)
    except (requests.RequestException, ValueError) as exc:
        return KeywordResult(keyword=keyword, found=False, error=str(exc))

    rank = None
    for i, place in enumerate(places, 1):
        if _name_matches(business, place.name or ""):
            rank = i
            break

    top_names = [p.name for p in places[:3] if p.name]
    return KeywordResult(
        keyword=keyword,
        found=rank is not None,
        rank=rank,
        competitors=top_names,
    )


def run_gap_analysis(
    business: str,
    location: str,
    keywords: Optional[List[str]] = None,
    limit: int = 20,
    timeout: int = 30,
    delay: float = 2.0,
) -> List[KeywordResult]:
    """Check every keyword and return the per-keyword results.

    A polite ``delay`` (seconds) is inserted between requests to avoid
    hammering Google.
    """
    keywords = keywords or DEFAULT_KEYWORDS
    results: List[KeywordResult] = []
    for kw in keywords:
        results.append(
            analyze_keyword(business, kw, location, limit=limit, timeout=timeout)
        )
        if delay:
            time.sleep(delay)
    return results


def _print_report(business: str, location: str, results: List[KeywordResult]) -> None:
    errors = [r for r in results if r.error]
    missing = [r for r in results if not r.error and not r.found]
    found = [r for r in results if not r.error and r.found]

    print(f"\nGap analysis for '{business}' in {location}\n" + "=" * 50)

    print(f"\n❌ MISSING — target with Google Ads ({len(missing)}):")
    if missing:
        for r in missing:
            comp = f"   (top: {', '.join(r.competitors)})" if r.competitors else ""
            print(f"   • {r.keyword}{comp}")
    else:
        print("   (none — appeared for every keyword)")

    print(f"\n✅ FOUND — already ranking ({len(found)}):")
    if found:
        for r in sorted(found, key=lambda x: x.rank or 999):
            print(f"   • {r.keyword} (rank #{r.rank})")
    else:
        print("   (none)")

    if errors:
        print(f"\n⚠️  ERRORS ({len(errors)}):")
        for r in errors:
            print(f"   • {r.keyword}: {r.error}")
        print(
            "\n   Note: HTTP 403 means Google blocked the request "
            "(common on cloud IPs). Run this from your own machine."
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find Google Maps keywords a business does NOT rank for."
    )
    parser.add_argument("business", help="Business name, e.g. 'Queen Nail'")
    parser.add_argument("location", help="City/area, e.g. 'Houston TX'")
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords to check (default: built-in nail list)",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="How many Maps results count as 'appearing' (default: 20)",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds to wait between searches (default: 2.0)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)

    keywords = (
        [k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else None
    )

    results = run_gap_analysis(
        args.business,
        args.location,
        keywords=keywords,
        limit=args.limit,
        timeout=args.timeout,
        delay=args.delay,
    )

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, ensure_ascii=False))
    else:
        _print_report(args.business, args.location, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
