"""Prevent annual range labels from being mistaken for report issuer names.

Titles such as ``2019_20년 지속가능경영보고서`` and ``2022/23년 ...`` are annual
period labels, not issuer statements.  Strip only recognized YYYY_YY / YYYY-YY /
YYYY/YYYY ranges before separator/path parsing; actual affiliate names remain
fail-closed conflicts.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "orchestrator/g0_report_entity_policy.py"
TEST = ROOT / "tests/test_g0_report_entity_alignment.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


RANGE_PATTERN = r"(?<!\\d)(?:19|20)\\d{2}\\s*[_/／-]\\s*(?:(?:19|20)\\d{2}|\\d{2})\\s*년?(?!\\d)"


def patch_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    old_clean = '''def _clean_issuer_prefix(prefix: str) -> str:\n    text = unquote(str(prefix or "")).replace("_", " ").replace("-", " ")\n    text = re.sub(r"(?<!\\d)(?:19|20)\\d{2}(?!\\d)", " ", text)\n'''
    new_clean = '''def _clean_issuer_prefix(prefix: str) -> str:\n    text = unquote(str(prefix or ""))\n    text = re.sub(\n        r"(?<!\\d)(?:19|20)\\d{2}\\s*[_/／-]\\s*(?:(?:19|20)\\d{2}|\\d{2})\\s*년?(?!\\d)",\n        " ",\n        text,\n    )\n    text = text.replace("_", " ").replace("-", " ")\n    text = re.sub(r"(?<!\\d)(?:19|20)\\d{2}(?!\\d)", " ", text)\n'''
    text = replace_once(text, old_clean, new_clean, "range-year cleanup")

    old_explicit = '''    idx, _ = min(positions, key=lambda x: x[0])\n    prefix = raw[:idx]\n    prefix = re.split(r"[|/\\\\:]+", prefix)[-1]\n    core = _clean_issuer_prefix(prefix)\n'''
    new_explicit = '''    idx, _ = min(positions, key=lambda x: x[0])\n    prefix = raw[:idx]\n    # Remove an annual-range label before slash/colon splitting. Otherwise a title\n    # such as ``2022/23년 지속가능경영보고서`` leaves ``23년`` as a fake issuer.\n    prefix = re.sub(\n        r"(?<!\\d)(?:19|20)\\d{2}\\s*[_/／-]\\s*(?:(?:19|20)\\d{2}|\\d{2})\\s*년?(?!\\d)",\n        " ",\n        prefix,\n    )\n    prefix = re.split(r"[|/\\\\:]+", prefix)[-1]\n    core = _clean_issuer_prefix(prefix)\n'''
    text = replace_once(text, old_explicit, new_explicit, "pre-split range-year cleanup")
    SOURCE.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    anchor = '''    def test_issuer_with_legal_form_and_verified_alias_aligns(self):\n        status, _ = entity_alignment(\n            self.discovery,\n            "Example Chemicals Co., Ltd. Sustainability Report 2023.pdf",\n            "",\n        )\n        self.assertEqual(status, "ALIGNED")\n'''
    addition = anchor + '''\n    def test_korean_range_year_prefix_is_not_mistaken_for_issuer(self):\n        for title in (\n            "2019_20년 지속가능경영보고서(국문)",\n            "2020_21년 지속가능경영보고서(국문)",\n            "2021-22년 지속가능경영보고서(국문)",\n            "2022/23년 지속가능경영보고서(국문)",\n        ):\n            with self.subTest(title=title):\n                status, issuers = entity_alignment(self.discovery, title, "")\n                self.assertEqual(status, "UNKNOWN")\n                self.assertEqual(issuers, [])\n\n    def test_range_year_cleanup_does_not_hide_actual_affiliate_issuer(self):\n        status, issuers = entity_alignment(\n            self.discovery,\n            "2022_23 Example Chemicals Energy Co., Ltd. Sustainability Report",\n            "",\n        )\n        self.assertEqual(status, "CONFLICT")\n        self.assertIn("examplechemicalsenergy", issuers)\n'''
    TEST.write_text(replace_once(text, anchor, addition, "range-year issuer regressions"), encoding="utf-8")


def main() -> int:
    patch_source()
    patch_test()
    subprocess.run([sys.executable, "-m", "unittest", "tests.test_g0_report_entity_alignment", "-v"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "py_compile", "orchestrator/g0_report_entity_policy.py"], cwd=ROOT, check=True)
    print("annual range-year issuer false positives removed without weakening affiliate mismatch checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
