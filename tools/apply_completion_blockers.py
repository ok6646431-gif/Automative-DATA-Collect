"""One-shot patcher for generic official-site mobile-host recovery.

This reuses the existing trusted patch workflow only as a transport mechanism.  It
modifies no company-specific configuration: when a DART-anchored corporate host is
unreachable, the recovery layer also probes the conventional m.<domain> endpoint
inside the same organization boundary.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "orchestrator/g0_official_site_recovery.py"
TEST = ROOT / "tests/test_g0_official_site_recovery.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


def patch_recovery() -> None:
    text = RECOVERY.read_text(encoding="utf-8")
    old = '''    bare = host.removeprefix("www.")
    hosts = _dedupe([host, bare, "www." + bare])
'''
    new = '''    # Mobile corporate front-ends are commonly published as m.<domain> while
    # remaining under the same DART-anchored organization boundary.  Probe that
    # conventional endpoint alongside bare/www variants; it is still only accepted
    # after the existing first-party crawl/evidence checks succeed.
    bare = host.removeprefix("www.").removeprefix("m.")
    hosts = _dedupe([host, bare, "www." + bare, "m." + bare])
'''
    RECOVERY.write_text(
        replace_once(text, old, new, "mobile official-host variant"),
        encoding="utf-8",
    )


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    anchor = '''    def test_bare_www_candidate_is_normalized_to_https(self):
        links = recovery._search_result_links(
            "https://www.google.com/search?q=corp",
            "Official site: www.example-corp.com/about",
        )
        self.assertEqual(["https://www.example-corp.com/about"], links)
'''
    replacement = anchor + '''
    def test_origin_variants_include_mobile_same_org_host(self):
        variants = recovery._origin_variants(
            "https://www.example-corp.com/legacy/index.do"
        )
        self.assertIn("https://m.example-corp.com/legacy/index.do", variants)
        self.assertIn("https://m.example-corp.com/", variants)
        self.assertIn(
            "https://www.example-corp.com/",
            recovery._origin_variants("https://m.example-corp.com/"),
        )
'''
    TEST.write_text(
        replace_once(text, anchor, replacement, "mobile origin regression test"),
        encoding="utf-8",
    )


def main() -> int:
    patch_recovery()
    patch_test()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_g0_official_site_recovery",
            "tests.test_g0_staged_official_recovery",
            "-v",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "add", "orchestrator/g0_official_site_recovery.py", "tests/test_g0_official_site_recovery.py"],
        cwd=ROOT,
        check=True,
    )
    print("generic mobile-host recovery patched and regression-tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
