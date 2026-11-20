#!/usr/bin/env python3
"""Fail-closed publishing of the slow 40-60 minute observation-station build.

Only invoked on ephemeral GitHub Actions main; never on a developer checkout.
Preserves newer concurrent commits and refuses overwrite if ANY station input changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TARGET = "data/obs/stations.json"
SOURCES = (TARGET, "obs_stations.py", "obs_extra_stations.csv", "obs_exclude_stations.csv")


def check_payload(raw: bytes) -> tuple[int, int]:
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("stations"), list):
        raise ValueError("stations.json needs a stations array")
    entries = obj["stations"]
    n, active = obj.get("n"), obj.get("n_active")
    if type(n) is not int or type(active) is not int or n < 1 or n != len(entries) or not 0 <= active <= n:
        raise ValueError("station count metadata is inconsistent")
    ids = set()
    active_count = 0
    for idx, station in enumerate(entries):
        if not isinstance(station, dict):
            raise ValueError(f"invalid station at index {idx}")
        sid = station.get("id")
        if not isinstance(sid, str) or not sid.strip() or sid in ids:
            raise ValueError(f"missing or duplicated stable station ID at {idx}")
        ids.add(sid)
        if type(station.get("active")) is not bool:
            raise ValueError(f"missing active boolean for {sid}")
        active_count += station["active"]
        for field, minimum, maximum in (("lat", -90, 90), ("lon", -180, 180)):
            value = station.get(field)
            if type(value) not in (int, float) or not minimum <= value <= maximum:
                raise ValueError(f"invalid {field} for {sid}")
    if active_count != active:
        raise ValueError("actual active count differs from manifest")
    return n, active


def git(*args, cwd: Path, must=True):
    p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if must and p.returncode:
        raise RuntimeError(f"git {args[0]} failed: {(p.stderr or p.stdout)[:300]}")
    return p


def blob(ref: str, path: str, root: Path) -> str | None:
    p = git("rev-parse", f"{ref}:{path}", cwd=root, must=False)
    return p.stdout.strip() if p.returncode == 0 else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", default=".")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--attempts", type=int, default=6)
    a = parser.parse_args(argv)
    root = Path(a.checkout).resolve()
    file = root / TARGET
    raw = file.read_bytes()
    n, active = check_payload(raw)
    print(f"Generated station registry validated: {n} records, {active} active")
    if not a.commit:
        print("DRY RUN ONLY: nothing committed or pushed")
        return 0
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Publishing is allowed only from GitHub Actions main branch")
    if not 1 <= a.attempts <= 12:
        raise ValueError("attempts must be 1..12")
    # These are the exact source versions used to build the generated station file.
    original = {path: blob("HEAD", path, root) for path in SOURCES}
    if original[TARGET] is None:
        raise RuntimeError("Input registry is not tracked; refuse to publish")
    git("config", "user.name", "obs-bot", cwd=root)
    git("config", "user.email", "obs-bot@users.noreply.github.com", cwd=root)
    for attempt in range(1, a.attempts + 1):
        git("fetch", "--quiet", "origin", "main", cwd=root)
        changed = [p for p in SOURCES if blob("origin/main", p, root) != original[p]]
        if changed:
            raise RuntimeError("Source/station registry changed during build; refuse stale overwrite: " + ", ".join(changed))
        # ONLY ephemeral GitHub Actions checkout, never a shared/developer workspace.
        git("reset", "--hard", "origin/main", cwd=root)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        git("add", "--", TARGET, cwd=root)
        if git("diff", "--cached", "--quiet", cwd=root, must=False).returncode == 0:
            print("Unchanged station registry; no commit needed")
            return 0
        git("commit", "-m", "obs: stations", cwd=root)
        if git("push", "origin", "HEAD:refs/heads/main", cwd=root, must=False).returncode == 0:
            print(f"Station registry safely published on attempt {attempt}")
            return 0
        if attempt < a.attempts:
            print(f"Push raced with another job; bounded retry {attempt}/{a.attempts}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError("Could not publish station registry after bounded retries; job must fail visibly")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print("STATION PUBLISH BLOCKED:", str(exc), file=sys.stderr)
        sys.exit(1)
