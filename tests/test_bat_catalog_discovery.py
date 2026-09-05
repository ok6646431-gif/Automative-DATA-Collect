import unittest

from orchestrator.bat_catalog_discovery import _ieps_board_id


class BATCatalogDiscoveryTests(unittest.TestCase):
    def test_ieps_board_id_ignores_query_string(self):
        self.assertEqual(
            _ieps_board_id('https://ieps.nier.go.kr/web/board/5/146/?pMENUMST_ID=95&page=2&CERT_TYP=6'),
            '146',
        )

    def test_ieps_board_id_accepts_relative_href(self):
        self.assertEqual(_ieps_board_id('/web/board/5/1898/?tab=seven'), '1898')

    def test_non_ieps_url_has_no_board_id(self):
        self.assertEqual(_ieps_board_id('https://www.me.go.kr/home/web/public_info/read.do?publicInfoId=763'), '')


if __name__ == '__main__':
    unittest.main()
