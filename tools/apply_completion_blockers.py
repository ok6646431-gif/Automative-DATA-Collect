"""One-shot generic report-discovery wiring patch.

The repository already contains a fail-closed JavaScript GET-form annual-report
recovery adapter and regression tests, but the live zero-touch runner never invokes
it.  In addition, Korean issuers often call the artifact a ``지속가능성보고서`` rather
than ``지속가능경영보고서``; that noun form was absent from the shared report-semantic
vocabulary and therefore failed before transport reconstruction.

This patch is company-agnostic:
* wire the existing JS-form adapter into live G0 before broader crawling;
* admit the ordinary Korean ``지속가능성보고서`` wording in strict/generic semantics;
* add regressions for both semantic gates; and
* run the existing fail-closed form reconstruction suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "orchestrator/zero_touch_runner.py"
STRICT = ROOT / "orchestrator/g0_report_enrichment.py"
GENERIC = ROOT / "orchestrator/g0_generic_js_report_recovery.py"
FORM_TEST = ROOT / "tests/test_g0_js_form_report_recovery.py"
STRICT_TEST = ROOT / "tests/test_g0_report_enrichment.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


def patch_runner() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from orchestrator import g0_generic_js_report_recovery\nfrom orchestrator import g0_kind_disclosure_recovery\n",
        "from orchestrator import g0_generic_js_report_recovery\nfrom orchestrator import g0_js_form_report_recovery\nfrom orchestrator import g0_kind_disclosure_recovery\n",
        "runner JS-form import",
    )
    text = replace_once(
        text,
        "    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)\n",
        "    documents = g0_generic_js_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_js_form_report_recovery.enrich(discovery, documents, audit)\n    documents = g0_data_attr_report_recovery.enrich(discovery, documents, audit)\n",
        "runner JS-form stage",
    )
    RUNNER.write_text(text, encoding="utf-8")


def patch_semantics() -> None:
    text = STRICT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서", "sustainability report",\n',
        '    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서",\n    "지속가능성보고서", "지속가능성 보고서", "sustainability report",\n',
        "strict Korean sustainability noun form",
    )
    STRICT.write_text(text, encoding="utf-8")

    text = GENERIC.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서",\n    "sustainability report", "integrated report", "esg report",\n',
        '    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서",\n    "지속가능성보고서", "지속가능성 보고서",\n    "sustainability report", "integrated report", "esg report",\n',
        "generic Korean sustainability noun form",
    )
    GENERIC.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = FORM_TEST.read_text(encoding="utf-8")
    anchor = '''    def test_local_report_control_is_admitted_without_download_word(self):\n        controls = extract_form_report_controls(self.html, 2020, 2026)\n        self.assertEqual(len(controls), 1)\n        self.assertEqual(controls[0]["year"], 2022)\n        self.assertEqual(controls[0]["function"], "requestAnnual")\n        self.assertEqual(controls[0]["args"], ["file-22"])\n        self.assertEqual(controls[0]["year_evidence"], "LOCAL_DOM")\n'''
    addition = anchor + '''\n    def test_korean_sustainability_noun_form_is_admitted(self):\n        html = self.html.replace("[2022] SUSTAINABILITY REPORT", "2022 지속가능성보고서")\n        controls = extract_form_report_controls(html, 2020, 2026)\n        self.assertEqual(len(controls), 1)\n        self.assertEqual(controls[0]["year"], 2022)\n        self.assertEqual(controls[0]["function"], "requestAnnual")\n'''
    FORM_TEST.write_text(
        replace_once(text, anchor, addition, "JS-form Korean noun regression"),
        encoding="utf-8",
    )

    text = STRICT_TEST.read_text(encoding="utf-8")
    anchor = '''    def test_sustainability_report_filename_is_accepted(self):\n        self.assertTrue(strong_report_semantics(\n            "다운로드",\n            "https://official.example/pdf/회사_지속가능경영보고서_2024_F.pdf",\n            "https://official.example/sustainability/",\n        ))\n'''
    addition = anchor + '''\n    def test_korean_sustainability_noun_report_filename_is_accepted(self):\n        self.assertTrue(strong_report_semantics(\n            "2025 KCC 지속가능성보고서",\n            "https://official.example/pdf/2025_KCC_지속가능성보고서.pdf",\n            "https://official.example/esg/reports",\n        ))\n'''
    STRICT_TEST.write_text(
        replace_once(text, anchor, addition, "strict Korean noun regression"),
        encoding="utf-8",
    )


def main() -> int:
    patch_runner()
    patch_semantics()
    patch_tests()
    subprocess.run(
        [
            sys.executable, "-m", "unittest",
            "tests.test_g0_js_form_report_recovery",
            "tests.test_g0_report_enrichment",
            "tests.test_g0_scripted_report_enrichment",
            "-v",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable, "-m", "py_compile",
            "orchestrator/zero_touch_runner.py",
            "orchestrator/g0_report_enrichment.py",
            "orchestrator/g0_generic_js_report_recovery.py",
            "orchestrator/g0_js_form_report_recovery.py",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git", "add",
            "orchestrator/zero_touch_runner.py",
            "orchestrator/g0_report_enrichment.py",
            "orchestrator/g0_generic_js_report_recovery.py",
            "tests/test_g0_js_form_report_recovery.py",
            "tests/test_g0_report_enrichment.py",
        ],
        cwd=ROOT,
        check=True,
    )
    print("JS-form annual-report recovery wired and Korean report semantics regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
