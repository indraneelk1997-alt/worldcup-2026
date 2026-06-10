"""
S20 Phase 2a v2: enumerate FBref's full competition catalog.

Why: Phase 2a v1 confirmed the league_dict overlay merges correctly,
but the FBref name guess ("Champions League") didn't match any
competition_name on FBref's /en/comps/ index. Rather than guess strings
one at a time, dump every competition_name FBref actually serves so we
can pick the right strings for CL/EL/Conference/Copa/AFCON/Asian/Gold/
WC-qualifying in one pass.

Source: the leagues.html cached by Phase 2a v1 at
~/soccerdata/data/FBref/leagues.html (we don't re-fetch — saves a
rate-limited request).

Output: prints every (competition_name, gender, governing_body, url)
row from each comps table on the FBref index page.

Run:
    uv run python src/load/v2_ingest/_probe_fbref_catalog.py

Deletable after we extract the names we need into league_dict.json.
Does not touch DB. Does not write any config.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import html

CACHE = Path.home() / "soccerdata" / "data" / "FBref" / "leagues.html"

# Strings to highlight as "interesting" for our S20 scope.
HIGHLIGHTS = [
    "champion", "europa", "conference",
    "copa", "conmebol",
    "africa", "afcon", "caf cup",
    "asian", "afc ",
    "gold", "concacaf",
    "ofc", "oceania",
    "euro",
    "world cup", "fifa",
    "qualif",
    "nations league",
    "friend",
]


def main() -> int:
    bar = "=" * 64
    print(f"\n{bar}\n  S20 Phase 2a v2 — FBref competition catalog dump\n{bar}")

    if not CACHE.exists():
        print(f"  cache miss: {CACHE}")
        print(f"  re-run _probe_cl_path_a.py first to populate the cache.")
        return 1

    print(f"  reading: {CACHE}")
    print(f"  size: {CACHE.stat().st_size:,} bytes")

    tree = html.parse(str(CACHE))
    tables = tree.xpath("//table[contains(@id, 'comps')]")
    print(f"  found {len(tables)} comp tables on the page\n")

    all_rows = []
    for ti, t in enumerate(tables):
        table_id = t.get("id", "?")
        rows = t.xpath(".//tbody/tr")
        print(f"  table[{ti}] id='{table_id}': {len(rows)} rows")
        for r in rows:
            # competition name is in a th with data-stat='league_name'
            name_th = r.xpath(".//th[@data-stat='league_name']")
            if not name_th:
                continue
            name = (name_th[0].text_content() or "").strip()
            url_a = name_th[0].xpath(".//a/@href")
            url = url_a[0] if url_a else ""

            # gender / governing_body cells if present (data-stat names vary)
            def cell(stat: str) -> str:
                td = r.xpath(f".//td[@data-stat='{stat}']")
                return (td[0].text_content() or "").strip() if td else ""

            gender = cell("gender")
            level = cell("comp_level")
            country = cell("country")
            comp_type = cell("comp_type") or cell("league_type")

            all_rows.append({
                "table": table_id,
                "name": name,
                "gender": gender,
                "level": level,
                "country": country,
                "type": comp_type,
                "url": url,
            })

    print(f"\n  total competition rows: {len(all_rows)}\n")

    # Full dump — every row
    print(f"{'-'*64}\nFULL CATALOG:\n{'-'*64}")
    for row in all_rows:
        print(
            f"  [{row['table']:24}] '{row['name']}'  "
            f"gender={row['gender']!r}  level={row['level']!r}  "
            f"country={row['country']!r}  type={row['type']!r}"
        )
        print(f"      url: {row['url']}")

    # Highlighted subset — likely matches for our S20 scope
    print(f"\n{'-'*64}\nHIGHLIGHTED (matches our scope keywords):\n{'-'*64}")
    matches = []
    for row in all_rows:
        if any(kw in row["name"].lower() for kw in HIGHLIGHTS):
            matches.append(row)
    for row in matches:
        print(
            f"  '{row['name']}'  "
            f"(gender={row['gender']}, level={row['level']}, "
            f"country={row['country']}, type={row['type']})"
        )
        print(f"      url: {row['url']}")
    print(f"\n  ({len(matches)} highlighted of {len(all_rows)} total)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
