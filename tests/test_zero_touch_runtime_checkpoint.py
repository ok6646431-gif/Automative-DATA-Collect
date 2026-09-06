import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import zero_touch_discovery as discovery


class RuntimeCheckpointTests(unittest.TestCase):
    def test_checkpoint_survives_discovery_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "generated"
            argv = [
                "zero_touch_discovery.py",
                "--company-name", "Example Corp",
                "--out-dir", str(out),
                "--start-year", "2020",
                "--max-pages", "60",
            ]
            with patch.object(sys, "argv", argv), patch.object(
                discovery, "discover", side_effect=RuntimeError("synthetic failure")
            ):
                with self.assertRaises(RuntimeError):
                    discovery.main()

            checkpoint = json.loads(
                (out / "Discovery_Runtime_Checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["company"], "Example Corp")
            self.assertEqual(checkpoint["status"], "ERROR")
            self.assertEqual(checkpoint["runtime_parameters"]["max_pages"], 60)
            self.assertIn("synthetic failure", checkpoint["error"])


if __name__ == "__main__":
    unittest.main()
