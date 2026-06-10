"""
Setup script — install the in-repo soccerdata league overlay into the
user's ~/soccerdata/config/ directory.

Run after a fresh clone, or any time data/config/league_dict.json
changes in this repo.

Why this exists: soccerdata reads ~/soccerdata/config/league_dict.json
at import time and merges it on top of its built-in LEAGUE_DICT
(soccerdata/_config.py:184–193). That gives us a mechanism to enable
additional FBref competitions (CL/EL/Conference/internationals/WCQ/…)
without forking the library. But the file lives outside the repo, so
without this script the overlay is per-machine and not reproducible
on a fresh checkout.

Merge semantics:
  - In-repo entries WIN on key conflicts (repo is canonical).
  - User-only entries in the existing file are PRESERVED.
  - Identical entries are no-op.
  - Any existing file is backed up to <name>.json.bak before writing.
  - Idempotent — safe to re-run.

Run:
    uv run python src/tools/setup_soccerdata_overlay.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Resolve repo root from this script's location:
#   src/tools/setup_soccerdata_overlay.py → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IN_REPO_OVERLAY = REPO_ROOT / "data" / "config" / "league_dict.json"

USER_CONFIG_DIR = Path.home() / "soccerdata" / "config"
USER_OVERLAY = USER_CONFIG_DIR / "league_dict.json"
BACKUP = USER_OVERLAY.with_suffix(".json.bak")


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    bar = "=" * 64
    print(f"\n{bar}\n  setup_soccerdata_overlay\n{bar}")

    if not IN_REPO_OVERLAY.exists():
        print(f"  FAIL: in-repo overlay not found at\n    {IN_REPO_OVERLAY}")
        return 1

    print(f"  in-repo  : {IN_REPO_OVERLAY}")
    print(f"  user file: {USER_OVERLAY}")

    in_repo = json.loads(IN_REPO_OVERLAY.read_text("utf8"))
    print(f"\n  in-repo overlay has {len(in_repo)} entries:")
    for k in sorted(in_repo):
        print(f"    - {k}")

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not USER_OVERLAY.exists():
        print(f"\n  user overlay does not exist — writing fresh.")
        USER_OVERLAY.write_text(_dump(in_repo), "utf8")
        print(f"\n  ✅ wrote {len(in_repo)} entries to {USER_OVERLAY}")
        return 0

    existing = json.loads(USER_OVERLAY.read_text("utf8"))
    print(f"\n  user overlay exists, {len(existing)} entries:")
    for k in sorted(existing):
        print(f"    - {k}")

    # Compute diff
    added = sorted(k for k in in_repo if k not in existing)
    overlapped = [k for k in in_repo if k in existing]
    user_only = sorted(k for k in existing if k not in in_repo)
    identical = sorted(
        k for k in overlapped
        if json.dumps(existing[k], sort_keys=True)
           == json.dumps(in_repo[k], sort_keys=True)
    )
    conflicted = sorted(set(overlapped) - set(identical))

    def show(label: str, items: list[str]) -> None:
        print(f"  {label:35} {items if items else 'none'}")

    print()
    show("new in this run:", added)
    show("identical (no-op):", identical)
    show("conflicted (will be replaced):", conflicted)
    show("user-only (preserved):", user_only)

    if not added and not conflicted:
        print(f"\n  ✅ nothing to do — user file already matches in-repo overlay.")
        return 0

    shutil.copy2(USER_OVERLAY, BACKUP)
    print(f"\n  backed up existing → {BACKUP}")

    merged = {**existing, **in_repo}  # in-repo wins on conflict
    USER_OVERLAY.write_text(_dump(merged), "utf8")

    print(f"\n  ✅ wrote merged overlay ({len(merged)} entries total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
