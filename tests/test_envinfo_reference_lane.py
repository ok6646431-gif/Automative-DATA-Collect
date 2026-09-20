import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))
from envinfo_reference_lane import keep_envinfo_out_of_official_annual_lane


class EnvinfoReferenceLaneTests(unittest.TestCase):
    def test_reports_remain_in_source_lane_and_cannot_inflate_official_count(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            official = root / '01_사용자자료' / '04_지속가능경영보고서'
            source = root / '01_사용자자료' / '03_환경정보공개시스템' / '사업장' / '첨부자료'
            policy = root / '01_사용자자료' / '06_회사환경정책' / '환경경영' / 'ENVINFO_공개근거'
            for folder in (official, source, policy):
                folder.mkdir(parents=True)
            original = source / '2022_환경부문보고서.pdf'
            original.write_bytes(b'ENVINFO original attachment')
            duplicate = official / 'ENVINFO공개연도_2022_환경부문보고서.pdf'
            duplicate.write_bytes(original.read_bytes())
            real = official / '기업_지속가능경영보고서_2022.pdf'
            real.write_bytes(b'corporate original')
            policy_doc = policy / 'ENVINFO공개연도_2022_환경정책.pdf'
            policy_doc.write_bytes(b'policy')

            def legacy_promoter(*_args):
                return [duplicate, policy_doc]

            promoted = keep_envinfo_out_of_official_annual_lane(legacy_promoter)(None, root, {}, '기업')
            self.assertEqual(promoted, [policy_doc])
            self.assertTrue(original.exists(), 'original ENVINFO attachment must remain available')
            self.assertFalse(duplicate.exists(), 'copied ENVINFO PDF must not enter official annual lane')
            self.assertTrue(real.exists(), 'independent corporate annual original must remain')
            self.assertEqual(list(official.glob('*.pdf')), [real])

    def test_all_promoter_created_files_in_official_lane_are_removed_regardless_of_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            official = root / '01_사용자자료' / '04_지속가능경영보고서'
            official.mkdir(parents=True)
            copied = official / '공식본처럼보이는_2024.pdf'
            copied.write_bytes(b'ENVINFO attachment copy')
            fn = keep_envinfo_out_of_official_annual_lane(lambda *_: [copied])
            self.assertEqual(fn(None, root, {}, ''), [])
            self.assertFalse(copied.exists())

    def test_repeated_source_rows_share_one_promoted_path_without_double_unlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            official = root / '01_사용자자료' / '04_지속가능경영보고서'
            original = root / '01_사용자자료' / '03_환경정보공개시스템' / '사업장' / '첨부자료' / '보고서.pdf'
            official.mkdir(parents=True)
            original.parent.mkdir(parents=True)
            original.write_bytes(b'original preserved')
            copied = official / 'ENVINFO공개연도_2022_보고서.pdf'
            copied.write_bytes(original.read_bytes())
            fn = keep_envinfo_out_of_official_annual_lane(lambda *_: [copied, copied])
            self.assertEqual(fn(None, root, {}, ''), [])
            self.assertFalse(copied.exists())
            self.assertTrue(original.exists())


if __name__ == '__main__':
    unittest.main()
