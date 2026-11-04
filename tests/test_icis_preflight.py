import unittest
import requests

from collectors.icis_preflight import classify_preflight_error


class ICISPreflightTests(unittest.TestCase):
    def test_http_errors_remain_http_errors(self):
        cases = {
            400: "REMOTE_HTTP_REJECTED",
            401: "REMOTE_ACCESS_RESTRICTED",
            403: "REMOTE_ACCESS_RESTRICTED",
            404: "REMOTE_ENDPOINT_NOT_FOUND",
            410: "REMOTE_ENDPOINT_NOT_FOUND",
            429: "REMOTE_HTTP_UNAVAILABLE",
            500: "REMOTE_HTTP_UNAVAILABLE",
            503: "REMOTE_HTTP_UNAVAILABLE",
        }
        for code, state in cases.items():
            with self.subTest(status=code):
                r = requests.Response()
                r.status_code = code
                r.url = "https://icis.mcee.go.kr/prtr/prtrInfo/entrpsSearch.do"
                with self.assertRaises(requests.HTTPError) as raised:
                    r.raise_for_status()
                self.assertEqual((state, code), classify_preflight_error(raised.exception))

    def test_transport_error_has_no_http_reply(self):
        for failure in (requests.ConnectionError("DNS"), requests.ConnectTimeout("timeout")):
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(
                    ("REMOTE_HOST_UNREACHABLE", None),
                    classify_preflight_error(failure),
                )


if __name__ == "__main__":
    unittest.main()
