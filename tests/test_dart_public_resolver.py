import unittest

from orchestrator.dart_public_resolver import extract_select_keys, query_variants


class TestDartPublicResolver(unittest.TestCase):
    def test_initial_brand_variant(self):
        variants = query_variants("HD현대삼호")
        self.assertIn("HD현대삼호", variants)
        self.assertIn("에이치디현대삼호", variants)
        self.assertIn("에이치디현대삼호 주식회사", variants)

    def test_encoded_search_result_url(self):
        payload = "https%3A%2F%2Fenglishdart.fss.or.kr%2Fdsbc001%2FselectPopup.ax%3FselectKey%3D00332468"
        self.assertIn("00332468", extract_select_keys(payload))

    def test_google_redirect_style_url(self):
        payload = '<a href="/url?q=https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00332468&amp;sa=U">result</a>'
        self.assertIn("00332468", extract_select_keys(payload))


if __name__ == "__main__":
    unittest.main()
