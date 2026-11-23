"""Verify source-independent completeness of a published run before sealing it.

Only fields confirmed present in the *same* run ('existing') or successfully
staged and waited for ('staged') count. This checker does not invent frames.
"""
from typing import Iterable


def require_complete_frames(model: str, expected: Iterable[str],
                            existing: Iterable[str], staged: Iterable[str]) -> None:
    requested = set(expected)
    if not requested:
        raise RuntimeError(f"{model}: expected-frame inventory is empty")
    available = set(existing) | set(staged)
    missing = sorted(requested - available)
    if missing:
        detail = ", ".join(missing[:5])
        raise RuntimeError(
            f"{model}: {len(missing)}/{len(requested)} required forecast "
            f"frames unavailable (e.g. {detail}); publication not finalized"
        )
