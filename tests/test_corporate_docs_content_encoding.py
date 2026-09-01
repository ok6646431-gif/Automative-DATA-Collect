import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collectors'))
from corporate_docs_collect import download_one


class FakeResponse:
    status_code = 200

    def __init__(self, body, content_type='text/html', content_length=None, content_encoding=None):
        self.body = body
        self.url = 'https://official.example/page'
        self.headers = {'Content-Type': content_type}
        if content_length is not None:
            self.headers['Content-Length'] = str(content_length)
        if content_encoding:
            self.headers['Content-Encoding'] = content_encoding

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def raise_for_status(self): return None
    def iter_content(self, size): yield self.body


class EncodedResponseTests(unittest.TestCase):
    def test_encoded_html_does_not_compare_decoded_bytes_to_wire_content_length(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'page.html'
            decoded = b'<!doctype html><html><body>compressed source</body></html>'
            response = FakeResponse(decoded, content_length=17, content_encoding='gzip')
            session = MagicMock(); session.get.return_value = response

            _, count, ctype = download_one(
                session,
                {'source_url': 'https://official.example/page', 'expected_extension': 'html'},
                target,
                0,
            )

            self.assertEqual(count, len(decoded))
            self.assertEqual(target.read_bytes(), decoded)
            self.assertEqual(ctype, 'text/html')
            self.assertEqual(session.get.call_count, 1)
            headers = session.get.call_args.kwargs['headers']
            self.assertEqual(headers.get('Accept-Encoding'), 'identity')
            self.assertNotIn('Range', headers)

    def test_interrupted_encoded_html_restarts_from_zero_without_range(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'page.html'
            decoded = b'<!doctype html><html><body>full source page</body></html>'
            cut = 19

            class Interrupted(FakeResponse):
                def iter_content(self, size):
                    yield decoded[:cut]
                    raise requests.exceptions.ConnectionError('stream interrupted')

            first = Interrupted(decoded, content_length=15, content_encoding='gzip')
            second = FakeResponse(decoded, content_length=15, content_encoding='gzip')
            session = MagicMock(); session.get.side_effect = [first, second]

            with patch('corporate_docs_collect.time.sleep'):
                _, count, _ = download_one(
                    session,
                    {'source_url': 'https://official.example/page', 'expected_extension': 'html'},
                    target,
                    0,
                )

            self.assertEqual(count, len(decoded))
            self.assertEqual(target.read_bytes(), decoded)
            self.assertEqual(session.get.call_count, 2)
            second_headers = session.get.call_args_list[1].kwargs['headers']
            self.assertEqual(second_headers.get('Accept-Encoding'), 'identity')
            self.assertNotIn('Range', second_headers)


if __name__ == '__main__':
    unittest.main()
