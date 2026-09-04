import tempfile, unittest, zipfile
from pathlib import Path

from orchestrator.archive_user_dedup_v2 import canonicalize_user_envinfo


class ArchiveUserDedupV2Tests(unittest.TestCase):
    def test_envinfo_attachments_are_single_copy_and_reference_official_document(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / '기업_환경자료'
            site_a = root/'01_사용자자료'/'03_환경정보공개시스템'/'광주공장'/'첨부자료'
            site_b = root/'01_사용자자료'/'03_환경정보공개시스템'/'곡성공장'/'첨부자료'
            report_dir = root/'01_사용자자료'/'04_지속가능경영보고서'
            idx = root/'00_자료목록'
            for p in [site_a, site_b, report_dir, idx]: p.mkdir(parents=True, exist_ok=True)
            (idx/'README_먼저읽기.txt').write_text('Archive v2 사용 안내\n', encoding='utf-8')

            duplicate = b'%PDF-' + b'A'*5000 + b'%%EOF'
            unique = b'%PDF-' + b'B'*3000 + b'%%EOF'
            (site_a/'2020_지속가능경영보고서.pdf').write_bytes(duplicate)
            (site_b/'2021_지속가능경영보고서.pdf').write_bytes(duplicate)
            official = report_dir/'기업_지속가능경영보고서_2020.pdf'
            official.write_bytes(duplicate)
            (site_a/'2020_환경방침.pdf').write_bytes(unique)

            stats = canonicalize_user_envinfo(root)
            self.assertEqual(stats['envinfo_attachment_occurrences'], 3)
            self.assertEqual(stats['envinfo_attachment_unique_files'], 2)
            self.assertEqual(stats['envinfo_attachment_duplicate_files_removed'], 1)
            self.assertEqual(stats['envinfo_generated_crossfolder_files_removed'], 1)
            self.assertTrue(official.exists())

            central = root/'01_사용자자료'/'03_환경정보공개시스템'/'첨부자료_원문'
            central_files = [p for p in central.iterdir() if p.is_file()]
            self.assertEqual(len(central_files), 1)
            self.assertEqual(central_files[0].read_bytes(), unique)
            self.assertFalse((site_a/'2020_지속가능경영보고서.pdf').exists())
            self.assertFalse((site_b/'2021_지속가능경영보고서.pdf').exists())

            ref = idx/'ENVINFO_첨부자료_참조표.xlsx'
            self.assertTrue(ref.exists())
            with zipfile.ZipFile(ref) as zf:
                names = set(zf.namelist())
                self.assertIn('[Content_Types].xml', names)
                self.assertIn('xl/workbook.xml', names)
                self.assertIsNone(zf.testzip())
            readme = (idx/'README_먼저읽기.txt').read_text(encoding='utf-8')
            self.assertIn('ENVINFO_첨부자료_참조표.xlsx', readme)


if __name__ == '__main__': unittest.main()
