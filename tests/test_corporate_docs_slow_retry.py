import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collectors"))
from corporate_docs_collect import (
    DOWNLOAD_TIMEOUT,
    MAX_DOCUMENT_WALL_SECONDS,
    MAX_SLOW_DOCUMENT_WALL_SECONDS,
    SLOW_RETRY_READ_TIMEOUT_SECONDS,
    download_one,
    slow_wall_budget_for_length,
)


class FakeResponse:
    def __init__(self, body, status_code=200, content_range=""):
        self.body = body
        self.status_code = status_code
        self.url = "https://official.example/report.pdf"
        self.headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="report.pdf"',
            "Content-Length": str(len(body)),
        }
        if content_range:
            self.headers["Content-Range"] = content_range

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, _size):
        yield self.body


class SlowDocumentRetryTests(unittest.TestCase):
    def test_slow_budget_is_larger_but_absolutely_bounded(self):
        budget = slow_wall_budget_for_length(16 * 1024 * 1024)
        self.assertGreater(budget, MAX_DOCUMENT_WALL_SECONDS)
        self.assertLessEqual(budget, MAX_SLOW_DOCUMENT_WALL_SECONDS)

    def test_retry_gets_longer_read_timeout_after_real_progress(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "report.pdf"
            full = b"%PDF-" + (b"x" * 200000)
            cut = 100000

            class Interrupted(FakeResponse):
                def __init__(self):
                    super().__init__(full)
                    self.headers["Content-Length"] = str(len(full))

                def iter_content(self, _size):
                    yield full[:cut]
                    raise requests.exceptions.ReadTimeout("slow official server")

            second = FakeResponse(full)
            session = unittest.mock.MagicMock()
            session.get.side_effect = [Interrupted(), second]

            with patch("corporate_docs_collect.time.sleep"):
                _, count, _ = download_one(
                    session,
                    {
                        "source_url": "https://official.example/report.pdf",
                        "expected_extension": "pdf",
                        "verification_status": "VERIFIED",
                    },
                    target,
                    0,
                )

            self.assertEqual(count, len(full))
            self.assertEqual(target.read_bytes(), full)
            first_timeout = session.get.call_args_list[0].kwargs["timeout"][1]
            second_timeout = session.get.call_args_list[1].kwargs["timeout"][1]
            self.assertLessEqual(first_timeout, DOWNLOAD_TIMEOUT[1])
            self.assertGreater(second_timeout, DOWNLOAD_TIMEOUT[1])
            self.assertLessEqual(second_timeout, SLOW_RETRY_READ_TIMEOUT_SECONDS)
            self.assertIn("Range", session.get.call_args_list[1].kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
