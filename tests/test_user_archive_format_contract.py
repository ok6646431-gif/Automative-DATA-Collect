import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))
import archive_builder as ab


class UserArchiveFormatContractTests(unittest.TestCase):
    def test_review_user_layer_exposes_only_finished_pdf_and_xlsx(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'pkg'; arc=Path(td)/'arc'; root.mkdir(); arc.mkdir()
            for name,_ in ab.REVIEW_REPORT_FILES:
                (root/name).write_bytes(b'dummy')
            created,pdf_present=ab.build_review_report_user(root,arc,'회사')
            self.assertTrue(pdf_present)
            self.assertEqual({p.suffix.lower() for p in created},{'.pdf','.xlsx'})
            self.assertFalse(any(p.suffix.lower() in {'.html','.json','.jsonl'} for p in (arc/ab.USER_ROOT).rglob('*') if p.is_file()))

    def test_corporate_html_prefers_live_official_url_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'pkg'; arc=Path(td)/'arc'; docs=root/'output'/'CORP_DOCS'; docs.mkdir(parents=True); arc.mkdir()
            src=docs/'page.html'; src.write_text('<html><body>raw</body></html>',encoding='utf-8')
            fields=['collection_status','stored_path','document_type','title','report_year','original_filename','source_url']
            with (docs/'document_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerow({'collection_status':'DOWNLOADED','stored_path':'output/CORP_DOCS/page.html','document_type':'ENVIRONMENTAL_POLICY','title':'환경정책','report_year':'2026','original_filename':'환경정책.html','source_url':'https://example.com/policy'})
            calls=[]
            def fake_live(url,dst):
                calls.append(url); Path(dst).write_bytes(b'%PDF-1.4\n%%EOF'); return True,''
            with mock.patch.object(ab,'render_url_pdf',side_effect=fake_live):
                created,rows=ab.build_corporate_user(root,arc,'회사')
            self.assertEqual(calls,['https://example.com/policy'])
            self.assertEqual(len(created),1)
            self.assertEqual(created[0].suffix.lower(),'.pdf')
            self.assertFalse(any(p.suffix.lower()=='.html' for p in (arc/ab.USER_ROOT).rglob('*') if p.is_file()))
            self.assertTrue(rows[0]['user_archive_path'].endswith('.pdf'))


if __name__ == '__main__':
    unittest.main()
