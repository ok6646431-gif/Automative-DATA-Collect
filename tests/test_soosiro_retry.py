import unittest
from unittest.mock import patch

import requests

from collectors import soosiro_collect


class FakeResponse:
    def __init__(self, status_code=200, text='{"list":[]}'):
        self.status_code=status_code
        self.text=text

    def raise_for_status(self):
        if self.status_code >= 400:
            err=requests.HTTPError(f"{self.status_code}")
            err.response=self
            raise err


class SoosiroRetryTests(unittest.TestCase):
    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_timeout_is_retried_then_succeeds(self, post, _sleep):
        post.side_effect=[requests.ReadTimeout("temporary"), FakeResponse(200)]
        response=soosiro_collect._post("https://example.test", data={}, headers={}, attempts=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)

    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_transient_503_is_retried(self, post, _sleep):
        post.side_effect=[FakeResponse(503), FakeResponse(200)]
        response=soosiro_collect._post("https://example.test", data={}, headers={}, attempts=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)

    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_non_transient_404_fails_without_retry(self, post, _sleep):
        post.return_value=FakeResponse(404)
        with self.assertRaises(requests.HTTPError):
            soosiro_collect._post("https://example.test", data={}, headers={}, attempts=3)
        self.assertEqual(post.call_count, 1)

    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_http_200_html_shell_is_retried_until_valid_json_list(self, post, _sleep):
        post.side_effect=[
            FakeResponse(200,"<html><body>temporary error</body></html>"),
            FakeResponse(200,'{"list":[]}'),
        ]
        response,obj,rows=soosiro_collect._post_list_json(
            "https://example.test",data={},headers={},attempts=3
        )
        self.assertEqual(response.status_code,200)
        self.assertEqual(obj,{"list":[]})
        self.assertEqual(rows,[])
        self.assertEqual(post.call_count,2)

    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_http_200_wrong_json_contract_is_retried(self, post, _sleep):
        post.side_effect=[
            FakeResponse(200,'{"error":"temporary"}'),
            FakeResponse(200,'{"list":[]}'),
        ]
        _,_,rows=soosiro_collect._post_list_json(
            "https://example.test",data={},headers={},attempts=3
        )
        self.assertEqual(rows,[])
        self.assertEqual(post.call_count,2)

    @patch("collectors.soosiro_collect.time.sleep", return_value=None)
    @patch("collectors.soosiro_collect.requests.post")
    def test_persistent_http_200_invalid_payload_fails_closed(self, post, _sleep):
        post.return_value=FakeResponse(200,"<html>still broken</html>")
        with self.assertRaises(soosiro_collect.SoosiroResponseContractError):
            soosiro_collect._post_list_json(
                "https://example.test",data={},headers={},attempts=3
            )
        self.assertEqual(post.call_count,3)


if __name__ == "__main__":
    unittest.main()
