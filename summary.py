"""
Turns .checkclaim/verdicts.jsonl into something a person can actually
read, instead of raw JSON lines. Read-only, doesn't touch the log.
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone


def _log_path(repo_dir):
    return os.path.join(repo_dir, ".checkclaim", "verdicts.jsonl")


def load_turns(repo_dir):
    path = _log_path(repo_dir)
    if not os.path.exists(path):
        return None

    turns = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except Exception:
                continue
    return turns


def build_report(turns):
    timestamps = [t["ts"] for t in turns if "ts" in t]
    days = sorted({datetime.fromtimestamp(ts, tz=timezone.utc).date() for ts in timestamps})

    status_counts = Counter()
    claim_type_counts = Counter()
    unrecognized = 0
    stale = 0
    no_evidence = 0

    for turn in turns:
        for r in turn.get("results", []):
            status = r.get("status", "UNKNOWN")
            status_counts[status] += 1
            ctype = r.get("claim_type")
            if ctype is None:
                unrecognized += 1
                continue
            claim_type_counts[ctype] += 1
            if status == "UNKNOWN":
                out = r.get("output") or ""
                desc = r.get("evidence_desc") or ""
                if "stale" in out:
                    stale += 1
                elif "no recorded run" in desc:
                    no_evidence += 1

    total_claims = sum(status_counts.values())

    lines = []
    lines.append(f"turns logged: {len(turns)}")
    if days:
        lines.append(f"active days: {len(days)} ({days[0]} to {days[-1]})")
    else:
        lines.append("active days: 0")
    lines.append(f"claims scored: {total_claims}")
    lines.append("")
    lines.append("verdicts:")
    for status in ("VERIFIED", "CONTRADICTION", "UNKNOWN"):
        n = status_counts.get(status, 0)
        pct = (n / total_claims * 100) if total_claims else 0
        lines.append(f"  {status:14s} {n:4d}  ({pct:.0f}%)")
    lines.append("")
    lines.append("claim types seen:")
    if claim_type_counts:
        for ctype, n in claim_type_counts.most_common():
            lines.append(f"  {ctype:20s} {n}")
    else:
        lines.append("  none recognized yet")
    lines.append("")
    lines.append("why the UNKNOWNs happened:")
    lines.append(f"  claim text not recognized:  {unrecognized}")
    lines.append(f"  evidence was stale:         {stale}")
    lines.append(f"  no evidence recorded:       {no_evidence}")

    return "\n".join(lines)
