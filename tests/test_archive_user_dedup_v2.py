import hashlib, tempfile, unittest, zipfile
from pathlib import Path

from pypdf import PdfWriter

from orchestrator.archive_user_dedup_v2 import canonicalize_user_envinfo


def write_blank_pdf(path: Path, width: float, height: float, metadata: dict[str, str]):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    writer.add_metadata(metadata)
    with path.open('wb') as f:
        writer.write(f)


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
            self.assertEqual(stats['sustainability_semantic_duplicate_files_removed'], 0)
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

    def test_same_year_semantic_pdf_duplicate_prefers_official_annual_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / '기업_환경자료'
            report_dir = root/'01_사용자자료'/'04_지속가능경영보고서'
            idx = root/'00_자료목록'
            report_dir.mkdir(parents=True)
            idx.mkdir(parents=True)
            (idx/'README_먼저읽기.txt').write_text('Archive v2 사용 안내\n', encoding='utf-8')

            official = report_dir/'기업_지속가능경영보고서_2022.pdf'
            generated_duplicate = report_dir/'ENVINFO공개연도_2022_기업_지속가능경영보고서.pdf'
            generated_distinct = report_dir/'ENVINFO공개연도_2022_다른보고서.pdf'
            other_year = report_dir/'ENVINFO공개연도_2021_기업_지속가능경영보고서.pdf'

            write_blank_pdf(official, 595, 842, {'/Title': 'Official annual copy'})
            write_blank_pdf(generated_duplicate, 595, 842, {'/Title': 'ENVINFO promoted copy', '/Producer': 'different metadata'})
            write_blank_pdf(generated_distinct, 612, 792, {'/Title': 'Different same-year report'})
            write_blank_pdf(other_year, 595, 842, {'/Title': 'Same rendering but different year'})

            self.assertNotEqual(
                hashlib.sha256(official.read_bytes()).hexdigest(),
                hashlib.sha256(generated_duplicate.read_bytes()).hexdigest(),
                'Fixture must prove raw-PDF hashes can differ while rendered structure is equal',
            )

            stats = canonicalize_user_envinfo(root)

            self.assertEqual(stats['sustainability_semantic_candidate_years'], ['2022'])
            self.assertEqual(stats['sustainability_semantic_duplicate_files_removed'], 1)
            self.assertGreater(stats['sustainability_semantic_duplicate_bytes_saved'], 0)
            self.assertEqual(stats['sustainability_semantic_failures'], [])
            self.assertEqual(stats['sustainability_semantic_engine'], 'PYPDF_PAGE_RENDER_STRUCTURE_SHA256_V1')
            self.assertTrue(official.exists())
            self.assertFalse(generated_duplicate.exists())
            self.assertTrue(generated_distinct.exists(), 'Different same-year PDF must never be removed')
            self.assertTrue(other_year.exists(), 'Same rendering in another year must never be merged')

            ref = idx/'ENVINFO_첨부자료_참조표.xlsx'
            self.assertTrue(ref.exists())
            readme = (idx/'README_먼저읽기.txt').read_text(encoding='utf-8')
            self.assertIn('페이지 표시 구조까지 동일한 경우에만', readme)


if __name__ == '__main__': unittest.main()
