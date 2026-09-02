import unittest

from orchestrator.dart_public_resolver import (
    company_result_probe,
    extract_company_codes,
    extract_select_keys,
    query_variants,
)


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

    def test_onclick_result_row_without_selectkey(self):
        payload = """
        <table><tr>
          <td><a onclick="setCrp('00332468','에이치디현대삼호 주식회사')">에이치디현대삼호 주식회사</a></td>
          <td>전라남도 영암군</td>
        </tr></table>
        """
        self.assertEqual(extract_company_codes(payload, "HD현대삼호"), ["00332468"])

    def test_hidden_code_result_row(self):
        payload = """
        <ul><li>
          <input type="hidden" name="textCrpCik" value="00332468" />
          <span>에이치디현대삼호(주)</span>
        </li></ul>
        """
        self.assertIn("00332468", extract_company_codes(payload, "HD현대삼호"))

    def test_unrelated_eight_digit_number_is_not_taken(self):
        payload = """
        <script>var staticBuild=20260902;</script>
        <table><tr><td>HD현대중공업 주식회사</td><td onclick="pick('00123456')">선택</td></tr></table>
        """
        self.assertEqual(extract_company_codes(payload, "HD현대삼호"), [])

    def test_probe_is_bounded_and_contains_only_matching_context(self):
        payload = """
        <table>
          <tr><td onclick="pick('00332468')">에이치디현대삼호 주식회사</td></tr>
          <tr><td onclick="pick('00123456')">다른회사 주식회사</td></tr>
        </table>
        """
        probe = company_result_probe(payload, "HD현대삼호")
        self.assertEqual(len(probe), 1)
        self.assertEqual(probe[0]["candidate_codes"], ["00332468"])
        self.assertIn("에이치디현대삼호", probe[0]["text"])


if __name__ == "__main__":
    unittest.main()
