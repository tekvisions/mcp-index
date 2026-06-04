#!/usr/bin/env python3
"""One-time backfill: reconstruct each server's `rank_history` from the daily data.json
snapshots already committed to git, then write it back into the live data.json.

The movement-tracking feature persists rank_history going forward, but The MCP Index
has been refreshing daily for days already — those snapshots are sitting in git history.
This mines them so registry-position movement (▲/▼) is real and visible immediately,
instead of waiting days for the series to fill in from scratch.

rank = 1-based position in each snapshot's freshest-first `servers` list (older
snapshots predate the `rank` field, so it's derived from list order). score = the
server's `updated_at` timestamp. Keyed on the stable server id (`name`).

Run from the repo dir:  python3 backfill_history.py
Idempotent: it rebuilds rank_history purely from git + merges into the current file.
After running, build_data.py reads this as prior history and extends it with today.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")


def _git(*args) -> str:
    return subprocess.run(["git", "-C", HERE, *args], capture_output=True, text=True).stdout


def _snapshots() -> list[dict]:
    """Every committed revision of data.json, oldest→newest, parsed."""
    shas = _git("log", "--format=%H", "--reverse", "--", "data.json").split()
    out = []
    for sha in shas:
        raw = _git("show", f"{sha}:data.json")
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    if not os.path.exists(DATA):
        print("no data.json — run build_data.py first", file=sys.stderr)
        return 1
    cur = json.load(open(DATA))

    # name -> {date: {date, rank, score}}  (dict keyed by date dedupes same-day re-runs)
    hist: dict[str, dict] = {}
    snaps = _snapshots()
    for snap in snaps:
        date = snap.get("generated_date") or (snap.get("generated_at") or "")[:10]
        if not date:
            continue
        servers = snap.get("servers", [])
        for idx, srv in enumerate(servers):
            key = srv.get("name")
            if not key:
                continue
            # use the stored rank if the snapshot has one, else derive from list order
            # (the list is already sorted freshest-first, so position == rank).
            rank = srv.get("rank")
            if not isinstance(rank, int):
                rank = idx + 1
            hist.setdefault(key, {})[date] = {
                "date": date, "rank": rank, "score": srv.get("updated_at"),
            }

    injected = 0
    for srv in cur.get("servers", []):
        key = srv.get("name")
        # MERGE git-derived points with any rank_history already on the live record,
        # keyed by date — never overwrite. The live points are canonical (a daily build
        # may have run without being committed to git), so they win on a same-date clash.
        merged: dict = {}
        for p in hist.get(key, {}).values():
            if p.get("date"):
                merged[p["date"]] = p
        for p in (srv.get("rank_history") or []):
            if isinstance(p, dict) and p.get("date"):
                merged[p["date"]] = p   # live wins
        series = sorted(merged.values(), key=lambda p: p["date"])[-90:]
        if series:
            srv["rank_history"] = series
            injected += 1

    json.dump(cur, open(DATA, "w"), indent=2)
    print(f"backfilled rank_history for {injected}/{len(cur.get('servers', []))} servers "
          f"from {len(snaps)} git snapshots", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
