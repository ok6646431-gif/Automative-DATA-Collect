import csv, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import archive_builder as ab


class EnvInfoUserFidelityTests(unittest.TestCase):
    def test_uses_full_section_static_reconstruction_and_labels_output(self):
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

            def fake_static(src,pdf):
                self.assertEqual(Path(src).name,'2020_ABC_예시사업장.html')
                Path(pdf).parent.mkdir(parents=True,exist_ok=True); Path(pdf).write_bytes(b'%PDF-1.4\n%%EOF')
                return True,''
            with patch.object(ab,'render_envinfo_static_pdf',side_effect=fake_static) as static:
                created,failures,_=ab.build_envinfo_user(root,archive,{'ENVINFO':{'ABC'}},{})
            self.assertEqual(failures,[])
            static.assert_called_once()
            names=[Path(x).name for x in created]
            self.assertTrue(any('전체내용정적재현본.pdf' in x for x in names),names)
            self.assertTrue(any('출처안내.txt' in x for x in names),names)
            notice=[Path(x) for x in created if '출처안내.txt' in Path(x).name][0].read_text(encoding='utf-8')
            self.assertIn('전체 등록 항목',notice)
            self.assertIn('90_시스템원본',notice)

    def test_static_html_expands_sections_and_removes_runtime_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/'raw.html'; out=Path(td)/'print.html'
            raw.write_text(
                '<html><head><link href="/css/site.css"></head><body>'
                '<div class="inquiry_wrap"><div class="colleft">menu</div>'
                '<div class="colright"><div class="inquiry_cont" style="display:none">'
                '<h3>사업현황</h3><table><tr><td>효성</td></tr></table>'
                '</div></div></div><script>hideTabs()</script></body></html>',
                encoding='utf-8'
            )
            ab.prepare_envinfo_static_html(raw,out)
            text=out.read_text(encoding='utf-8')
            self.assertNotIn('<script>',text)
            self.assertIn('https://www.env-info.kr/css/site.css',text)
            self.assertIn('.inquiry_cont {',text)
            self.assertIn('display:block !important',text)
            self.assertIn('.inquiry_wrap .colleft',text)


    def test_clean_fallback_html_strips_site_css_but_preserves_disclosure_content(self):
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/'raw.html'; out=Path(td)/'clean.html'
            raw.write_text(
                '<html><head><style>.inquiry_cont *{color:transparent}</style>'
                '<link rel="stylesheet" href="/css/bad.css"></head><body>'
                '<div class="inquiry_cont" style="display:none">'
                '<h3 class="title">사업현황</h3>'
                '<table class="legacy"><tr><th>사업장</th><td style="color:white">울산공장</td></tr></table>'
                '<script>eraseText()</script></div></body></html>',
                encoding='utf-8'
            )
            ab.prepare_envinfo_clean_html(raw,out)
            text=out.read_text(encoding='utf-8')
            self.assertIn('사업현황',text)
            self.assertIn('울산공장',text)
            self.assertIn('<table>',text)
            self.assertNotIn('color:transparent',text)
            self.assertNotIn('bad.css',text)
            self.assertNotIn('eraseText',text)
            self.assertNotIn('class="legacy"',text)
            self.assertIn('ENVINFO_CLEAN_PRINT_CSS' if False else 'border-collapse:collapse',text)

    def test_static_render_uses_clean_fallback_only_after_severe_text_collapse(self):
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/'raw.html'; pdf=Path(td)/'out.pdf'
            raw.write_text(
                '<html><head></head><body><div class="inquiry_cont">'
                + ('환경정보 공개내용 ' * 80) +
                '</div></body></html>',
                encoding='utf-8'
            )
            def fake_render(html,pdf_path):
                Path(pdf_path).write_bytes(b'%PDF-1.4\n' + b'0'*1200 + b'\n%%EOF')
                return True,''
            with patch.object(ab,'render_html_pdf',side_effect=fake_render) as render, \
                 patch.object(ab,'_needs_envinfo_clean_fallback',side_effect=[True,False]) as need:
                ok,msg=ab.render_envinfo_static_pdf(raw,pdf)
            self.assertTrue(ok)
            self.assertIn('clean semantic fallback',msg)
            self.assertEqual(render.call_count,2)
            self.assertEqual(need.call_count,2)


    def test_static_reconstruction_failure_is_review_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'pkg'; archive=Path(td)/'archive'
            env=root/'output'/'ENVINFO'; detail=env/'raw_detail'; detail.mkdir(parents=True)
            (root/'Company_Profile.json').write_text(json.dumps({'canonical_sites':[]},ensure_ascii=False),encoding='utf-8')
            (root/'Requested_Scope.json').write_text('{}',encoding='utf-8')
            with (env/'discovery.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['year','compId','compNm']); w.writeheader(); w.writerow({'year':'2021','compId':'XYZ','compNm':'예시공장'})
            (detail/'2021_XYZ_예시공장.html').write_text('<html></html>',encoding='utf-8')
            with (env/'attachment_index.csv').open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=['compId','collection_status']); w.writeheader()
            with patch.object(ab,'render_envinfo_static_pdf',return_value=(False,'missing sections')):
                created,failures,_=ab.build_envinfo_user(root,archive,{'ENVINFO':{'XYZ'}},{})
            self.assertEqual(created,[])
            self.assertEqual(len(failures),1)
            self.assertEqual(failures[0]['issue_type'],'ENVINFO_STATIC_RECONSTRUCTION_FAILED')

if __name__=='__main__': unittest.main()
