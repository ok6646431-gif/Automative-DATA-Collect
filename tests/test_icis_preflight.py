import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests

from collectors import prtr_collect, chem_stats_collect

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

    def test_collectors_report_http_response_without_false_host_outage(self):
        cases = (
            (prtr_collect, "PRTR", {
                "start_year": 2020, "end_year": 2024,
                "search_terms": [{"term": "example"}],
            }, 404, "REMOTE_ENDPOINT_NOT_FOUND", 22),
            (chem_stats_collect, "CHEM_STATS", {
                "years": [2024], "search_terms": ["example"],
            }, 403, "REMOTE_ACCESS_RESTRICTED", 72),
        )
        for collector, source, config, http_code, status, exit_code in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                previous_dir = Path.cwd()
                try:
                    os.chdir(directory)
                    Path("request.json").write_text(json.dumps({
                        "sources": {source: config},
                    }), encoding="utf-8")
                    response = requests.Response()
                    response.status_code = http_code
                    response.url = "https://icis.mcee.go.kr/"
                    mocked = Mock()
                    mocked.post.return_value = response
                    with patch.object(collector, "session", return_value=mocked):
                        actual = collector.main("request.json")
                    result = json.loads(
                        (Path("output") / source / "status.json").read_text(encoding="utf-8"))
                    self.assertEqual(exit_code, actual)
                    self.assertEqual(status, result["status"])
                    self.assertEqual(http_code, result["preflight_http_status"])
                finally:
                    os.chdir(previous_dir)

    def test_transport_error_has_no_http_reply(self):
        for failure in (requests.ConnectionError("DNS"), requests.ConnectTimeout("timeout")):
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(
                    ("REMOTE_HOST_UNREACHABLE", None),
                    classify_preflight_error(failure),
                )


if __name__ == "__main__":
    unittest.main()
