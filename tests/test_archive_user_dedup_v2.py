import hashlib, importlib, tempfile, unittest, zipfile
from pathlib import Path

from pypdf import PdfWriter

# The full unittest discovery corpus may import archive_user_dedup_v2 before another
# test module installs optional PDF dependencies. This regression specifically exercises
# the pypdf-backed semantic comparison, so reload the module after pypdf is importable
# instead of inheriting a stale module-level PdfReader=None from discovery order.
import orchestrator.archive_user_dedup_v2 as archive_user_dedup_v2
archive_user_dedup_v2 = importlib.reload(archive_user_dedup_v2)
canonicalize_user_envinfo = archive_user_dedup_v2.canonicalize_user_envinfo


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


    def test_promoted_envinfo_report_is_retained_in_sustainability_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / '기업_환경자료'
            site = root/'01_사용자자료'/'03_환경정보공개시스템'/'본사'/'첨부자료'
            report_dir = root/'01_사용자자료'/'04_지속가능경영보고서'
            idx = root/'00_자료목록'
            for p in [site, report_dir, idx]:
                p.mkdir(parents=True, exist_ok=True)
            (idx/'README_먼저읽기.txt').write_text('Archive v2 사용 안내\n', encoding='utf-8')

            payload = b'%PDF-' + b'R'*5000 + b'%%EOF'
            original = site/'2020_SR_2020_kr.pdf'
            promoted = report_dir/'ENVINFO공개연도_2020_SR_2020_kr.pdf'
            original.write_bytes(payload)
            promoted.write_bytes(payload)

            stats = canonicalize_user_envinfo(root)

            self.assertTrue(promoted.exists(), 'Human-facing sustainability folder must keep the categorized copy')
            central = root/'01_사용자자료'/'03_환경정보공개시스템'/'첨부자료_원문'
            self.assertFalse(
                central.exists() and any(p.is_file() and p.read_bytes()==payload for p in central.iterdir())
            )
            self.assertEqual(stats['envinfo_generated_crossfolder_files_removed'], 1)

            ref = idx/'ENVINFO_첨부자료_참조표.csv'
            self.assertTrue(ref.exists())
            import csv
            with ref.open(encoding='utf-8-sig', newline='') as fh:
                records=list(csv.DictReader(fh))
            targets={str(r.get('최종_보존경로') or '') for r in records}
            self.assertIn(promoted.relative_to(root).as_posix(),targets)

    def test_chained_attachment_promotion_and_semantic_dedup_resolves_to_physical_report(self):
        import csv

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / '기업_환경자료'
            site = root/'01_사용자자료'/'03_환경정보공개시스템'/'광주공장'/'첨부자료'
            report_dir = root/'01_사용자자료'/'04_지속가능경영보고서'
            idx = root/'00_자료목록'
            for p in [site, report_dir, idx]:
                p.mkdir(parents=True, exist_ok=True)
            (idx/'README_먼저읽기.txt').write_text('Archive v2 사용 안내\n', encoding='utf-8')

            promoted = report_dir/'ENVINFO공개연도_2022_기업_지속가능경영보고서.pdf'
            official = report_dir/'기업_지속가능경영보고서_2022.pdf'
            write_blank_pdf(promoted, 595, 842, {'/Title': 'ENVINFO promoted copy'})
            write_blank_pdf(official, 595, 842, {'/Title': 'Official annual copy'})
            original = site/'2022_기업_지속가능경영보고서.pdf'
            original.write_bytes(promoted.read_bytes())
            original_digest = hashlib.sha256(original.read_bytes()).hexdigest()

            self.assertNotEqual(
                hashlib.sha256(promoted.read_bytes()).hexdigest(),
                hashlib.sha256(official.read_bytes()).hexdigest(),
            )

            stats = canonicalize_user_envinfo(root)

            self.assertEqual(stats['envinfo_generated_crossfolder_files_removed'], 1)
            self.assertEqual(stats['sustainability_semantic_duplicate_files_removed'], 1)
            self.assertFalse(promoted.exists())
            self.assertTrue(official.exists())

            ref = idx/'ENVINFO_첨부자료_참조표.csv'
            with ref.open(encoding='utf-8-sig', newline='') as fh:
                rows = list(csv.DictReader(fh))

            original_rel = original.relative_to(root).as_posix()
            official_rel = official.relative_to(root).as_posix()
            source_row = next(r for r in rows if r['원래_사용자경로'] == original_rel)
            self.assertEqual(source_row['최종_보존경로'], official_rel)
            self.assertEqual(source_row['SHA256'], original_digest)
            self.assertEqual(source_row['최종_보존_SHA256'], hashlib.sha256(official.read_bytes()).hexdigest())
            self.assertNotEqual(source_row['SHA256'], source_row['최종_보존_SHA256'])
            for row in rows:
                final = row['최종_보존경로']
                if final:
                    self.assertTrue((root/final).is_file(), f'stale final path: {final}')

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
