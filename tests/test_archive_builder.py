import csv, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"orchestrator"))
from archive_builder import build_archive


def write_csv(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0]) if rows else ["source_key"]
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


class ArchiveBuilderTests(unittest.TestCase):
    def test_builds_v2_user_and_system_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            profile={
                "company_id":"COMP1","company_display_name":"테스트화학","requested_company_name":"테스트화학",
                "site_candidates":[{"site_name_raw":"테스트공장","identity_status":"CONFIRMED","verification_state":"VERIFIED"}]
            }
            (root/"Company_Profile.json").write_text(json.dumps(profile,ensure_ascii=False),encoding="utf-8")
            (root/"Integration_Summary.json").write_text(json.dumps({"company_id":"COMP1"}),encoding="utf-8")
            for name in ["Master_Manifest.json","REVIEW_REQUIRED.json"]:
                (root/name).write_text("{}" if name.endswith("Manifest.json") else "[]",encoding="utf-8")
            write_csv(root/"Validation_Queue.csv",[])
            write_csv(root/"Coverage_Status.csv",[{"source_key":"ENVINFO","coverage_status":"MEETS_MINIMUM","collected_start":"2020","collected_end":"2024","next_action":""}])
            # Source-native identity is part of the scope contract. A canonical site by
            # itself must never be enough to admit a source ID, because a related legal
            # entity can share the same physical/canonical site.
            write_csv(root/"Source_Identity.csv",[{
                "source_key":"ENVINFO","source_site_id":"C1","match_status":"CONFIRMED","canonical_site_id":"SITE1",
                "source_site_name_raw":"테스트화학 테스트공장","source_address_raw":""
            }])

            env=root/"output"/"ENVINFO"; (env/"raw_attachments"/"2024"/"C1").mkdir(parents=True)
            att=env/"raw_attachments"/"2024"/"C1"/"조직도.png"; att.write_bytes(b"PNGDATA")
            env_report=env/"raw_attachments"/"2024"/"C1"/"지속가능경영보고서.pdf"; env_report.write_bytes(b"%PDF-env-report")
            write_csv(env/"attachment_index.csv",[{
                "year":"2024","compId":"C1","compNm":"테스트공장","section_id":"inquiry10","section_title":"전담조직","file_id":"F1","original_filename":"조직도.png",
                "stored_path":str(att.relative_to(root)),"bytes":str(att.stat().st_size),"sha256":"dummy","content_type":"image/png","importance":"CORE",
                "document_category":"ORGANIZATION_ROLE","collection_status":"DOWNLOADED","error":""
            },{
                "year":"2024","compId":"C1","compNm":"테스트공장","section_id":"inquiry26","section_title":"환경(지속가능)보고서 발간 현황","file_id":"F2","original_filename":"지속가능경영보고서.pdf",
                "stored_path":str(env_report.relative_to(root)),"bytes":str(env_report.stat().st_size),"sha256":"dummy-report","content_type":"application/pdf","importance":"SUPPORTING",
                "document_category":"OTHER_ENVINFO_EVIDENCE","collection_status":"DOWNLOADED","error":""
            }])
            write_csv(env/"discovery.csv",[{"year":"2024","compId":"C1","compNm":"테스트공장"}])
            (env/"raw_detail").mkdir(); (env/"raw_detail"/"2024_C1_테스트공장.html").write_text("<html><body>detail</body></html>",encoding="utf-8")

            clean=root/"output"/"CLEANSYS_AIR"; clean.mkdir(parents=True); (clean/"annual_rows.jsonl").write_text("",encoding="utf-8"); (clean/"candidates.json").write_text("[]",encoding="utf-8")
            water=root/"output"/"SOOSIRO_WATER"; water.mkdir(parents=True); (water/"annual_rows.jsonl").write_text("",encoding="utf-8"); (water/"daily_rows.jsonl").write_text("",encoding="utf-8"); (water/"fact_candidates.json").write_text("[]",encoding="utf-8")
            prtr=root/"output"/"PRTR"; prtr.mkdir(parents=True); write_csv(prtr/"discovery.csv",[]); (prtr/"detail_table_rows.jsonl").write_text("",encoding="utf-8")
            chem=root/"output"/"CHEM_STATS"; chem.mkdir(parents=True); write_csv(chem/"discovery.csv",[]); (chem/"detail_table_rows.jsonl").write_text("",encoding="utf-8")

            docs=root/"output"/"CORP_DOCS"; (docs/"raw_documents"/"SUSTAINABILITY_REPORT"/"2024").mkdir(parents=True)
            pdf=docs/"raw_documents"/"SUSTAINABILITY_REPORT"/"2024"/"D1_report.pdf"; pdf.write_bytes(b"%PDF-test")
            write_csv(docs/"document_index.csv",[{
                "document_id":"D1","canonical_site_id":"","site_name_raw":"","document_type":"SUSTAINABILITY_REPORT","importance":"CORE","title":"2024 지속가능경영보고서","report_year":"2024",
                "coverage_start":"2024-01-01","coverage_end":"2024-12-31","publication_date":"2025-06-01","original_filename":"report.pdf","stored_path":str(pdf.relative_to(root)),
                "source_locator":"https://official.example/report.pdf","retrieved_at":"2025-06-02T00:00:00Z","bytes":str(pdf.stat().st_size),"sha256":"dummy2","content_type":"application/pdf","verification_status":"VERIFIED","collection_status":"DOWNLOADED","notes":""
            }])

            summary=build_archive(root)
            archive=root/"Human_Archive"/"테스트화학_환경자료"
            self.assertTrue((archive/"01_사용자자료"/"03_환경정보공개시스템"/"테스트공장"/"첨부자료"/"2024_조직도.png").exists())
            self.assertTrue((archive/"01_사용자자료"/"03_환경정보공개시스템"/"테스트공장"/"첨부자료"/"2024_지속가능경영보고서.pdf").exists())
            self.assertTrue((archive/"01_사용자자료"/"04_지속가능경영보고서"/"ENVINFO공개연도_2024_지속가능경영보고서.pdf").exists())
            self.assertTrue((archive/"90_시스템원본"/"ENVINFO"/"raw_detail"/"2024_C1_테스트공장.html").exists())
            self.assertTrue((archive/"01_사용자자료"/"04_지속가능경영보고서"/"테스트화학_지속가능경영보고서_2024.pdf").exists())
            self.assertFalse((archive/"01_사용자자료"/"04_지속가능경영보고서"/"2024").exists())
            self.assertTrue((archive/"01_사용자자료"/"01_TMS"/"대기_CleanSYS"/"CleanSYS_대기TMS_정리.xlsx").exists())
            self.assertTrue((archive/"00_자료목록"/"전체자료목록.xlsx").exists())
            self.assertTrue((archive/"00_자료목록"/"확인필요_REVIEW_REQUIRED.xlsx").exists())
            self.assertTrue((root/"Human_Archive.zip").exists())
            self.assertEqual(summary["schema_version"],"2.0")
            self.assertEqual(summary["downloaded_documents"],1)
            self.assertEqual(summary["envinfo_promoted_references"],1)


if __name__=="__main__": unittest.main()
