"""Regression: upper-air fallback must not silently use a previous cycle."""
from pathlib import Path
import ast


def test_gfs_upper_source_uses_current_cycle_only():
    source = Path(__file__).resolve().parents[1].joinpath("nwp_maps.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    loops = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name) and node.target.id == "rr"
        and isinstance(node.iter, ast.Tuple)
    ]
    assert any(
        len(node.iter.elts) == 1
        and isinstance(node.iter.elts[0], ast.Name)
        and node.iter.elts[0].id == "run"
        and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == "exists" for child in ast.walk(node))
        for node in loops
    ), "GFS upper-air fallback must check only the current run"
