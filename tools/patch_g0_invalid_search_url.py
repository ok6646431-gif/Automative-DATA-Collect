from pathlib import Path

TARGET = Path("orchestrator/g0_official_site_recovery.py")
TEST = Path("tests/test_g0_official_site_recovery.py")

text = TARGET.read_text(encoding="utf-8")
old = '''def _blocked(url: str) -> bool:\n    host = (urlparse(url).hostname or "").casefold()\n    return not host or any(part in host for part in BLOCKED_HOST_PARTS)\n'''
new = '''def _blocked(url: str) -> bool:\n    # Search-result markup sometimes exposes breadcrumb/display text as if it were\n    # a URL (for example ``www.example.com › blog › post``). Treat a malformed\n    # locator as blocked instead of allowing one unrelated candidate to abort G0.\n    try:\n        host = (urlparse(url).hostname or "").casefold()\n    except ValueError:\n        return True\n    return not host or any(part in host for part in BLOCKED_HOST_PARTS)\n'''
if old not in text:
    raise SystemExit("_blocked anchor not found")
text = text.replace(old, new, 1)
TARGET.write_text(text, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = '''    def test_origin_variants_include_mobile_same_org_host(self):\n'''
case = '''    def test_malformed_breadcrumb_search_candidate_is_ignored(self):\n        html = """<html><body>\n          <cite>www.unrelated.example › blog › posts › malformed title</cite>\n          <cite>www.example-corp.com/company</cite>\n        </body></html>"""\n        links = recovery._search_result_links(\n            "https://www.google.com/search?q=corp", html\n        )\n        self.assertEqual(["https://www.example-corp.com/company"], links)\n\n'''
if marker not in tests:
    raise SystemExit("test insertion marker not found")
if "test_malformed_breadcrumb_search_candidate_is_ignored" not in tests:
    tests = tests.replace(marker, case + marker, 1)
TEST.write_text(tests, encoding="utf-8")
