import unittest

from orchestrator.g0_rename_chronology_recovery import (
    _decode_response_text,
    parse_official_name_chain,
    parse_resulting_name_chronology,
)


class FakeResponse:
    def __init__(self, payload: bytes, encoding="ISO-8859-1", apparent_encoding="utf-8"):
        self.content = payload
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class TestG0RenameChronologyRecovery(unittest.TestCase):
    def test_resulting_name_chronology_finds_immediate_predecessor(self):
        text = (
            "1978.09.26 : 대우조선공업(주) 설립 "
            "2002.03.16 : 대우조선해양(주)으로 상호 변경 "
            "2023.05.23 : 한화오션(주)로 상호 변경"
        )
        parsed = parse_resulting_name_chronology(text, "한화오션(주)")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["date"], "2023-05-23")
        self.assertEqual(parsed["predecessor"], "대우조선해양(주)")
        self.assertEqual(parsed["successor"], "한화오션(주)")

    def test_subsidiary_change_does_not_replace_main_company_chain(self):
        text = (
            "2002.03.16 : 대우조선해양(주)으로 상호 변경 "
            "2023.05.23 : 한화오션(주)로 상호 변경 "
            "2023.05.23 : 한화해양공정(산동)유한공사로 상호 변경"
        )
        parsed = parse_official_name_chain(text, "한화오션(주)")
        self.assertEqual(parsed["predecessor"], "대우조선해양(주)")
        self.assertEqual(parsed["date"], "2023-05-23")

    def test_decode_response_recovers_current_name_from_misdecoded_utf8(self):
        source = (
            "2002.03.16 : 대우조선해양(주)으로 상호 변경 "
            "2023.05.23 : 한화오션(주)로 상호 변경"
        )
        response = FakeResponse(source.encode("utf-8"))
        broken = response.text
        self.assertNotIn("한화오션", broken)
        fixed = _decode_response_text(response, "한화오션(주)")
        self.assertIn("한화오션", fixed)
        self.assertIn("대우조선해양", fixed)


if __name__ == "__main__":
    unittest.main()
