import unittest

from orchestrator.g0_public_disclosure_enrichment import parse_official_rename_text


class TestG0PublicDisclosureEnrichment(unittest.TestCase):
    def test_explicit_krx_style_rename_is_parsed(self):
        text = (
            "당사는 2000년 10월 23일 분할 신설되었습니다. "
            "2023년 5월 23일 임시주주총회에서 대우조선해양(주)에서 "
            "한화오션(주)로 상호가 변경되었습니다."
        )
        parsed = parse_official_rename_text(text, "한화오션(주)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["date"], "2023-05-23")
        self.assertEqual(parsed["predecessor"], "대우조선해양(주)")

    def test_other_company_rename_is_not_accepted(self):
        text = "2023년 5월 23일 A회사에서 B회사로 상호가 변경되었습니다."
        self.assertIsNone(parse_official_rename_text(text, "한화오션(주)"))


if __name__ == "__main__":
    unittest.main()
