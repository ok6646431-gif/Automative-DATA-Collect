import csv, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import archive_builder as ab


class EnvInfoUserFidelityTests(unittest.TestCase):
    def test_prefers_live_official_detail_render_and_labels_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'pkg'; archive=Path(td)/'archive'
            env=root/'output'/'ENVINFO'; detail=env/'raw_detail'
            detail.mkdir(parents=True)
            (root/'Company_Profile.json').write_text(json.dumps({'canonical_sites':[]},ensure_ascii=False),encoding='utf-8')
            (root/'Requested_Scope.json').write_text('{}',encoding='utf-8')
            with (env/'discovery.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['year','compId','compNm']); w.writeheader(); w.writerow({'year':'2020','compId':'ABC','compNm':'예시사업장'})
            (detail/'2020_ABC_예시사업장.html').write_text('<html><body>source response</body></html>',encoding='utf-8')
            with (env/'attachment_index.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['compId','collection_status']); w.writeheader()

            def fake_live(url,pdf):
                Path(pdf).parent.mkdir(parents=True,exist_ok=True); Path(pdf).write_bytes(b'%PDF-1.4\n%%EOF')
                self.assertIn('YEAR=2020',url); self.assertIn('COMP_ID=ABC',url)
                return True,''
            with patch.object(ab,'render_url_pdf',side_effect=fake_live) as live, patch.object(ab,'render_html_pdf') as local:
                created,failures,_=ab.build_envinfo_user(root,archive,{'ENVINFO':{'ABC'}},{})
            self.assertEqual(failures,[])
            live.assert_called_once(); local.assert_not_called()
            names=[Path(x).name for x in created]
            self.assertTrue(any('공식화면인쇄본.pdf' in x for x in names),names)
            self.assertTrue(any('출처안내.txt' in x for x in names),names)

    def test_local_html_fallback_is_explicitly_labeled(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'pkg'; archive=Path(td)/'archive'
            env=root/'output'/'ENVINFO'; detail=env/'raw_detail'; detail.mkdir(parents=True)
            (root/'Company_Profile.json').write_text(json.dumps({'canonical_sites':[]},ensure_ascii=False),encoding='utf-8')
            (root/'Requested_Scope.json').write_text('{}',encoding='utf-8')
            with (env/'discovery.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['year','compId','compNm']); w.writeheader(); w.writerow({'year':'2021','compId':'XYZ','compNm':'예시공장'})
            raw=detail/'2021_XYZ_예시공장.html'; raw.write_text('<html></html>',encoding='utf-8')
            with (env/'attachment_index.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['compId','collection_status']); w.writeheader()
            def fake_local(src,pdf):
                Path(pdf).parent.mkdir(parents=True,exist_ok=True); Path(pdf).write_bytes(b'%PDF-1.4\n%%EOF'); return True,''
            with patch.object(ab,'render_url_pdf',return_value=(False,'live failed')), patch.object(ab,'render_html_pdf',side_effect=fake_local):
                created,failures,_=ab.build_envinfo_user(root,archive,{'ENVINFO':{'XYZ'}},{})
            self.assertEqual(failures,[])
            names=[Path(x).name for x in created]
            self.assertTrue(any('수집HTML_재현본.pdf' in x for x in names),names)
            notice=[Path(x) for x in created if '출처안내.txt' in Path(x).name][0].read_text(encoding='utf-8')
            self.assertIn('원문 자체가 아님',notice)
            self.assertIn('90_시스템원본',notice)

if __name__=='__main__': unittest.main()
