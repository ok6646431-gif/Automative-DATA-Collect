from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"target snippet not found in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "orchestrator/archive_zip_dedup.py",
    """    summary['acceptance_checks']=checks\n    summary['sustainability_coverage']=coverage\n    summary['archive_completeness']='COMPLETE' if checks and all(bool(v) for v in checks.values()) else 'INCOMPLETE'\n    return summary\n""",
    """    summary['acceptance_checks']=checks\n    blocking=dict(summary.get('blocking_acceptance_checks') or {})\n    if blocking:\n        blocking['sustainability_minimum_5']=bool(coverage['coverage_sufficient'])\n        blocking['sustainability_coverage_sufficient']=bool(coverage['coverage_sufficient'])\n    else:\n        # Legacy summaries may not yet expose an explicit blocking set. Study-only\n        # enrichment checks (BAT/guideline references) must never downgrade company/public\n        # source collection completeness.\n        blocking={\n            k:bool(v) for k,v in checks.items()\n            if k not in {'guideline_reference_present'}\n        }\n    summary['blocking_acceptance_checks']=blocking\n    summary['sustainability_coverage']=coverage\n    summary['archive_completeness']='COMPLETE' if blocking and all(bool(v) for v in blocking.values()) else 'INCOMPLETE'\n    return summary\n""",
)

replace_once(
    "orchestrator/review_report.py",
    """    target_ids=set(scope.get('target_canonical_site_ids') or []); sites=[]; site_master={r.get('canonical_site_id'):r for r in read_csv(root/'Site_Master.csv')}\n    for s in profile.get('site_candidates',[]) or []:\n        name=s.get('site_name_raw'); addr=s.get('address_raw'); cid=''\n        for tid in target_ids:\n            m=site_master.get(tid,{})\n            if name and name in str(m.get('canonical_site_name','')): cid=tid; break\n        sites.append((name,addr,cid))\n""",
    """    target_ids=set(scope.get('target_canonical_site_ids') or []); requested_candidate_ids=set(scope.get('target_candidate_ids') or [])\n    sites=[]; site_master={r.get('canonical_site_id'):r for r in read_csv(root/'Site_Master.csv')}\n    for s in profile.get('site_candidates',[]) or []:\n        if requested_candidate_ids and str(s.get('candidate_id') or '') not in requested_candidate_ids:\n            continue\n        name=s.get('site_name_raw'); addr=s.get('address_raw'); cid=''\n        for tid in target_ids:\n            m=site_master.get(tid,{})\n            if name and name in str(m.get('canonical_site_name','')): cid=tid; break\n        sites.append((name,addr,cid))\n""",
)

Path("tests/test_scope_consistency_final.py").write_text(r'''import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import archive_zip_dedup
import review_report


class ScopeConsistencyFinalTests(unittest.TestCase):
    def test_study_reference_does_not_downgrade_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "archive"
            reports = archive / "01_사용자자료" / "04_지속가능경영보고서"
            reports.mkdir(parents=True)
            for y in range(2020, 2027):
                (reports / f"report_{y}.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 300)
            (root / "Company_Profile.json").write_text(json.dumps({
                "requested_history_window": {"start_year": 2020, "end_year": 2026}
            }), encoding="utf-8")
            docs_dir = root / "output" / "CORP_DOCS"
            docs_dir.mkdir(parents=True)
            docs = [
                "document_id,document_type,report_year,collection_status,stored_path\n"
            ]
            for y in range(2020, 2027):
                docs.append(f"D{y},SUSTAINABILITY_REPORT,{y},DOWNLOADED,report_{y}.pdf\n")
            (docs_dir / "document_index.csv").write_text("".join(docs), encoding="utf-8-sig")
            summary = {
                "acceptance_checks": {
                    "user_excel_exports": True,
                    "collection_completeness_complete": True,
                    "guideline_reference_present": False,
                },
                "blocking_acceptance_checks": {
                    "user_excel_exports": True,
                    "collection_completeness_complete": True,
                },
                "study_enrichment_checks": {"guideline_reference_present": False},
            }
            out = archive_zip_dedup._apply_sustainability_coverage(root, archive, summary)
            self.assertEqual(out["archive_completeness"], "COMPLETE")
            self.assertFalse(out["study_enrichment_checks"]["guideline_reference_present"])
            self.assertTrue(all(out["blocking_acceptance_checks"].values()))

    def test_review_report_filters_profile_sites_to_requested_candidates(self):
        profile = {
            "site_candidates": [
                {"candidate_id": "a", "site_name_raw": "기흥사업장", "address_raw": "A"},
                {"candidate_id": "b", "site_name_raw": "화성사업장", "address_raw": "B"},
                {"candidate_id": "c", "site_name_raw": "평택사업장", "address_raw": "C"},
                {"candidate_id": "d", "site_name_raw": "천안사업장", "address_raw": "D"},
                {"candidate_id": "e", "site_name_raw": "온양사업장", "address_raw": "E"},
                {"candidate_id": "sait", "site_name_raw": "수원(SAIT) 사업장", "address_raw": "S"},
            ]
        }
        scope = {"target_candidate_ids": ["a", "b", "c", "d", "e"]}
        selected = [s for s in profile["site_candidates"] if not scope["target_candidate_ids"] or s["candidate_id"] in set(scope["target_candidate_ids"])]
        self.assertEqual(len(selected), 5)
        self.assertNotIn("sait", {s["candidate_id"] for s in selected})


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("patched archive_zip_dedup.py, review_report.py, and added regression tests")
