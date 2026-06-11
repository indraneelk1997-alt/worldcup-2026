"""
_probe_wc2026_squads.py — S23 probe (deletable, mirrors other _probe_*).

OBSERVE the WC2026 squads Wikipedia DOM before writing the real parser
(ingest_wc2026_squads.py). The one thing pandas.read_html can't tell us is
which nation each squad table belongs to (the nation is a section heading,
not a table column). So this probe tests the core parser assumption:
"each squad wikitable's nearest preceding h2/h3 = its nation."

Full report is written to a txt file (terminal only gets a 3-line summary)
since the output is long.

Reports, no DB / no writes:
  * total wikitables vs squad-like tables (those with a 'Player' column)
  * the nearest-heading for the first few wikitables (association test)
  * a sample squad table's columns + first rows
  * the h2/h3 heading outline (how nations are nested)

    uv run python src/load/v2_ingest/_probe_wc2026_squads.py
"""
from __future__ import annotations

import io
import sys
import traceback
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
# Wikipedia rejects the default urllib UA; identify ourselves politely.
UA = "worldcup-2026-research/0.1 (contact: indraneelk1997@gmail.com)"
REPORT = Path("data/raw/wc2026/_probe_squads_report.txt")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    lines: list[str] = []  # full report buffer -> file
    summary: list[str] = []  # short -> terminal

    def w(s: str = "") -> None:
        lines.append(s)

    # Whole body guarded: on ANY error we still write the report (with the
    # traceback) so there's always an artifact to inspect.
    try:
        html = fetch(URL)
        w(f"html bytes: {len(html):,}")

        # --- pandas view: how many tables, how many look like squads? ---
        # pandas wants literal HTML wrapped in StringIO (not a bare string).
        tabs = pd.read_html(io.StringIO(html))
        squad_like = [t for t in tabs if any("Player" in str(c) for c in t.columns)]
        w(f"\npandas read_html -> {len(tabs)} tables total")
        w(f"squad-like (have a 'Player' column): {len(squad_like)}  (expect ~48)")
        summary.append(f"tables={len(tabs)}  squad-like={len(squad_like)} (~48?)")
        if squad_like:
            t = squad_like[0]
            w("\nsample squad table columns: " + str(list(t.columns)))
            w(t.head(3).to_string(index=False))

        # --- bs4 view: test nation<-heading association ---
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            w("\n[bs4 not installed] add it with `uv add beautifulsoup4` and re-run.")
            summary.append("bs4 NOT installed -> heading test skipped")
            soup = None
        else:
            soup = BeautifulSoup(html, "html.parser")

        if soup is not None:
            wikitables = soup.select("table.wikitable")
            w(f"\nbs4 table.wikitable count: {len(wikitables)}")
            summary.append(f"wikitables={len(wikitables)}")

            w("\nnearest-heading test (first 6 wikitables):")
            for tbl in wikitables[:6]:
                h = tbl.find_previous(["h3", "h2"])
                span = h.find("span", class_="mw-headline") if h else None
                heading = (span.get_text() if span else (h.get_text() if h else "?")).strip()
                ths = [th.get_text(strip=True) for th in tbl.find_all("th")][:8]
                w(f"  heading={heading!r:28}  th[:8]={ths}")

            w("\nheading outline (h2/h3, first 24):")
            for hh in soup.find_all(["h2", "h3"])[:24]:
                span = hh.find("span", class_="mw-headline")
                txt = (span.get_text() if span else hh.get_text()).strip()
                if txt:
                    w(f"  <{hh.name}> {txt!r}")
        rc = 0
    except Exception:
        tb = traceback.format_exc()
        w("\n!!! PROBE ERROR — traceback below !!!\n" + tb)
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print("probe done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
