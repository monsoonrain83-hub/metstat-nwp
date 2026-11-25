"""P0: no NWP climatology credential in URL/query, only request header.

Static AST test avoids loading heavy GRIB/cartography dependencies. A green
test is NOT proof that all other upload clients migrated from URL credentials.
"""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "nwp_maps.py"


def validate(src: str) -> list[str]:
    issues = []
    root = ast.parse(src, filename="nwp_maps.py")
    calls = []
    for node in ast.walk(root):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = ast.get_source_segment(src, node.args[0]) or ""
        if "nwp_upload.php?a=clim" not in target:
            continue
        calls.append(node)
        if "&key=" in target or "?key=" in target:
            issues.append("credential-in-query")
        if not (isinstance(node.func, ast.Attribute)
                and node.func.attr == "post"):
            issues.append("not-post")
        hdr = next((k.value for k in node.keywords if k.arg == "headers"), None)
        if not isinstance(hdr, ast.Dict):
            issues.append("missing-headers")
            continue
        keyed = {
            k.value: v for k, v in zip(hdr.keys, hdr.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        v = keyed.get("X-Upload-Key")
        if not (isinstance(v, ast.Attribute)
                and v.attr == "key"
                and isinstance(v.value, ast.Name)
                and v.value.id == "a"):
            issues.append("wrong-auth-header")
        redirect = next((k.value for k in node.keywords if k.arg == "allow_redirects"), None)
        if not isinstance(redirect, ast.Constant) or redirect.value is not False:
            issues.append("redirects-not-disabled")
    if len(calls) != 1:
        issues.append("unexpected-clim-call-count")
    return issues


class NwpURLCredentialGuard(unittest.TestCase):
    def test_real_nwp_source_has_header_only_clim_auth(self):
        self.assertEqual(validate(SOURCE.read_text(encoding="utf8")), [])

    def test_detect_query_credential_regression(self):
        src = SOURCE.read_text(encoding="utf8").replace(
            'nwp_upload.php?a=clim"',
            'nwp_upload.php?a=clim&key={a.key}"'
        )
        self.assertIn("credential-in-query", validate(src))

    def test_detect_redirect_regression(self):
        src = SOURCE.read_text(encoding="utf8").replace(
            "allow_redirects=False", "allow_redirects=True"
        )
        self.assertIn("redirects-not-disabled", validate(src))

    def test_detect_missing_header(self):
        src = SOURCE.read_text(encoding="utf8").replace(
            "headers={'X-Upload-Key': a.key}, timeout=120",
            "timeout=120"
        )
        self.assertIn("missing-headers", validate(src))


if __name__ == "__main__":
    unittest.main()
