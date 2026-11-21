#!/usr/bin/env python3
"""Fail-closed guard against replacing any published world model with an older cycle.

Run after building a verified candidate and fetching the world-data branch,
but BEFORE replacing any existing world files.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_cycle(value):
    if not isinstance(value, str):
        raise ValueError("missing init_utc")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("cycle must have UTC timezone")
    return dt.astimezone(timezone.utc)


def check_candidate(current_dir: Path, candidate_dir: Path):
    for model in ("gfs", "ecmwf", "gem"):
        candidate_path = candidate_dir / model / "manifest.json"
        new = json.loads(candidate_path.read_text(encoding="utf-8"))
        if new.get("model") != model or not new.get("full_globe") or new.get("mock"):
            raise ValueError(f"{model}: invalid candidate world manifest")
        new_cycle = parse_cycle(new.get("init_utc"))
        old_path = current_dir / model / "manifest.json"
        if not old_path.exists():
            continue
        old = json.loads(old_path.read_text(encoding="utf-8"))
        if old.get("model") != model:
            raise ValueError(f"{model}: corrupt current model manifest")
        old_cycle = parse_cycle(old.get("init_utc"))
        if new_cycle < old_cycle:
            raise RuntimeError(
                f"{model}: refusing stale global forecast {new_cycle.isoformat()} "
                f"over newer published {old_cycle.isoformat()}"
            )
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("current", type=Path)
    p.add_argument("candidate", type=Path)
    a = p.parse_args()
    check_candidate(a.current, a.candidate)
    print("WORLD_FRESHNESS_GUARD_PASSED", flush=True)
