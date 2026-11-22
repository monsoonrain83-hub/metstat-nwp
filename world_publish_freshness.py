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


SOURCE_ORDER = {
    'ecmwf': {'ecmwf_ifs': 0, 'ecmwf_ifs025': 1},
    'gfs': {'ncep_gfs013': 0, 'ncep_gfs025': 1},
    'gem': {'cmc_gem_gdps_15km': 0, 'cmc_gem_gdps': 0},
}


def prevent_field_regression(model, current, candidate, same_cycle):
    """Preserve all published fields; do not downgrade same-cycle source grids.

    Later forecast cycles may start on coarse-grid fallback because freshness
    takes precedence, but the same run must only keep or improve resolution.
    """
    old_fields = current.get('fields')
    new_fields = candidate.get('fields')
    if old_fields is None:  # Compatibility with pre-provenance/legacy manifests.
        return
    if not isinstance(old_fields, dict) or not isinstance(new_fields, dict):
        raise ValueError(f'{model}: invalid field collection for freshness check')
    dropped = set(old_fields) - set(new_fields)
    if dropped:
        raise RuntimeError(f'{model}: refusing loss of published fields: {sorted(dropped)}')
    if not same_cycle:
        return
    order = SOURCE_ORDER[model]
    for key, old in old_fields.items():
        new = new_fields[key]
        if not isinstance(old, dict) or not isinstance(new, dict):
            raise ValueError(f'{model}/{key}: invalid field provenance')
        old_source = old.get('field_source_domain')
        new_source = new.get('field_source_domain')
        if old_source not in order or new_source not in order:
            raise ValueError(f'{model}/{key}: unverified source domain in same-cycle release')
        if order[new_source] > order[old_source]:
            raise RuntimeError(
                f'{model}/{key}: refusing same-cycle resolution downgrade '
                f'{old_source} -> {new_source}')


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
        prevent_field_regression(model, old, new, new_cycle == old_cycle)
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("current", type=Path)
    p.add_argument("candidate", type=Path)
    a = p.parse_args()
    check_candidate(a.current, a.candidate)
    print("WORLD_FRESHNESS_GUARD_PASSED", flush=True)
