"""
S20 probe: discover which competitions FBref / ESPN / WhoScored expose.

Phase 1 only — discovery, not shape-fetching:
  - print available_leagues() per scraper
  - print a keyword-filtered subset (CL/EL/EURO/Copa/AFCON/Asian/WC/...)

Does NOT:
  - touch the DB
  - fetch any season data (no read_schedule / read_match etc.)
  - rely on network beyond whatever the scraper's class-level league
    catalog needs

Run:
    uv run python src/load/v2_ingest/_probe_competitions.py

Delete after S20 once findings are captured in
docs/v104_ingest_competitions.md (S18 probe pattern).
"""

from __future__ import annotations

import traceback

KEYWORDS = [
    # UEFA club
    "UEFA-Champions", "Champions League",
    "UEFA-Europa", "Europa League",
    "UEFA-Conference", "Conference League",
    # International senior tournaments
    "EURO", "Euro ",
    "Copa", "CONMEBOL",
    "AFCON", "Africa", "CAF",
    "Asian Cup", "AFC",
    "Gold Cup", "CONCACAF",
    "OFC", "Nations Cup", "Nations League",
    "FIFA", "World Cup", "WC",
    "qualific", "Qualif",
    "Friendl", "INT-", "International",
]


def get_leagues(scraper_cls):
    """Try class-level first, then default instance. Return (leagues, how)."""
    # try classmethod
    try:
        leagues = scraper_cls.available_leagues()
        return list(leagues), "classmethod"
    except TypeError:
        pass  # not a classmethod; try instance
    except Exception:
        # other error on class call — fall through to instance try
        pass

    # try default instance
    inst = scraper_cls()
    leagues = inst.available_leagues()
    return list(leagues), "default-instance"


def probe(name, scraper_cls):
    bar = "=" * 64
    print(f"\n{bar}\n  {name}\n{bar}")
    try:
        leagues, how = get_leagues(scraper_cls)
    except Exception as e:
        print(f"  FAILED to read available_leagues(): "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return

    print(f"  available_leagues() via: {how}")
    print(f"  total: {len(leagues)}")

    print(f"\n  --- ALL leagues (sorted) ---")
    for L in sorted(leagues):
        print(f"    {L}")

    print(f"\n  --- KEYWORD-FILTERED (CL/EL/EURO/WC/INT/qualif/...) ---")
    lowered = [k.lower() for k in KEYWORDS]
    matches = sorted(
        L for L in leagues
        if any(k in str(L).lower() for k in lowered)
    )
    for L in matches:
        print(f"    {L}")
    print(f"  ({len(matches)} keyword matches)")


def main():
    # Import lazily so a broken import in one scraper doesn't kill the
    # whole probe. WhoScored in particular pulls Selenium.
    scrapers = []
    for name, import_path in [
        ("FBref",     "soccerdata.FBref"),
        ("ESPN",      "soccerdata.ESPN"),
        ("WhoScored", "soccerdata.WhoScored"),
    ]:
        mod_path, _, cls_name = import_path.rpartition(".")
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            scrapers.append((name, cls))
        except Exception as e:
            print(f"[{name}] import failed: {type(e).__name__}: {e}")

    for name, cls in scrapers:
        try:
            probe(name, cls)
        except Exception as e:
            print(f"\n[{name}] probe crashed top-level: "
                  f"{type(e).__name__}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
