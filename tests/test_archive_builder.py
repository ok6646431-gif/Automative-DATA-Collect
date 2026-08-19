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
    def test_builds_human_facing_structure_and_indexes_documents(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"Company_Profile.json").write_text(json.dumps({"company_id":"COMP1","company_display_name":"테스트화학"},ensure_ascii=False),encoding="utf-8")
            (root/"Integration_Summary.json").write_text(json.dumps({"company_id":"COMP1"}),encoding="utf-8")
            for name in ["Master_Manifest.json","REVIEW_REQUIRED.json"]:
                (root/name).write_text("{}" if name.endswith("Manifest.json") else "[]",encoding="utf-8")
            write_csv(root/"Coverage_Status.csv",[{"source_key":"ENVINFO","coverage_status":"MEETS_MINIMUM","collected_start":"2020","collected_end":"2024","next_action":""}])
            write_csv(root/"Source_Identity.csv",[{"source_key":"ENVINFO","source_site_id":"C1","match_status":"CONFIRMED","canonical_site_id":"SITE1"}])
            env=root/"output"/"ENVINFO"; (env/"raw_attachments"/"2024"/"C1").mkdir(parents=True)
            att=env/"raw_attachments"/"2024"/"C1"/"조직도.png"; att.write_bytes(b"PNGDATA")
            write_csv(env/"attachment_index.csv",[{
                "year":"2024","compId":"C1","compNm":"테스트공장","section_title":"전담조직","file_id":"F1","original_filename":"조직도.png",
                "stored_path":str(att.relative_to(root)),"bytes":str(att.stat().st_size),"sha256":"dummy","content_type":"image/png","importance":"CORE",
                "document_category":"ORGANIZATION_ROLE","collection_status":"DOWNLOADED","error":""
            }])
            write_csv(env/"discovery.csv",[{"year":"2024","compId":"C1","compNm":"테스트공장"}])
            (env/"raw_detail").mkdir(); (env/"raw_detail"/"2024_C1_테스트공장.html").write_text("<html>detail</html>",encoding="utf-8")
            for source in ["PRTR","CHEM_STATS","CLEANSYS_AIR","SOOSIRO_WATER"]:
                p=root/"output"/source; p.mkdir(parents=True); (p/"status.json").write_text("{}",encoding="utf-8")
            docs=root/"output"/"CORP_DOCS"; (docs/"raw_documents"/"SUSTAINABILITY_REPORT"/"2024").mkdir(parents=True)
            pdf=docs/"raw_documents"/"SUSTAINABILITY_REPORT"/"2024"/"D1_report.pdf"; pdf.write_bytes(b"%PDF-test")
            write_csv(docs/"document_index.csv",[{
                "document_id":"D1","canonical_site_id":"","site_name_raw":"","document_type":"SUSTAINABILITY_REPORT","importance":"CORE","title":"2024 지속가능경영보고서","report_year":"2024",
                "coverage_start":"2024-01-01","coverage_end":"2024-12-31","publication_date":"2025-06-01","original_filename":"report.pdf","stored_path":str(pdf.relative_to(root)),
                "source_locator":"https://official.example/report.pdf","retrieved_at":"2025-06-02T00:00:00Z","bytes":str(pdf.stat().st_size),"sha256":"dummy2","content_type":"application/pdf","verification_status":"VERIFIED","collection_status":"DOWNLOADED","notes":""
            }])
            summary=build_archive(root)
            archive=root/"Human_Archive"/"테스트화학_환경자료"
            self.assertTrue((archive/"03_환경정보공개시스템"/"테스트공장"/"2024"/"ORGANIZATION_ROLE"/"조직도.png").exists())
            self.assertFalse((archive/"03_환경정보공개시스템"/"원본"/"raw_attachments").exists())
            self.assertTrue((archive/"04_지속가능경영보고서"/"2024"/"report.pdf").exists())
            self.assertTrue((archive/"00_자료목록"/"Document_Index.csv").exists())
            self.assertTrue((archive/"00_자료목록"/"핵심자료_목록.csv").exists())
            self.assertTrue((root/"Human_Archive.zip").exists())
            self.assertEqual(summary["downloaded_documents"],2)


if __name__=="__main__": unittest.main()
