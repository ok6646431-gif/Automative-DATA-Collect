from pathlib import Path
import textwrap

code_path = Path("orchestrator/g0_staged_official_recovery.py")
text = code_path.read_text(encoding="utf-8")

crawl_marker = "def crawl_official(http: base.Http, start_url: str, company: str, max_pages: int = 90):\n"
if crawl_marker not in text:
    raise SystemExit("crawl_official marker not found; refusing fuzzy patch")

helper = textwrap.dedent(r'''
def _dart_auxiliary_official_candidates(
    http: base.Http,
    start_url: str,
    company: str,
) -> List[str]:
    """Recover extra first-party seeds explicitly published by DART.

    Some DART company records expose both a generic Website and a deeper
    IR Website. A generic root can become a technically-live login/shell
    while the DART-published IR URL still points into the current corporate
    navigation. Only same-organization HTTP(S) URLs are retained, and this
    helper is consulted only after the primary DART surface proved thin.
    """
    try:
        legal, _ = base.resolve_legal_identity(http, company)
    except Exception:
        return []
    if not isinstance(legal, dict):
        return []

    values: List[str] = []
    for key in ("ir_website", "investor_website"):
        value = str(legal.get(key) or "").strip()
        if value:
            values.append(value)

    raw = str(legal.get("raw_text") or "")
    patterns = (
        r"(?i)\bIR\s+Website\s+((?:https?://)?[^\s]+)",
        r"(?i)\bInvestor(?:\s+Relations)?\s+Website\s+((?:https?://)?[^\s]+)",
    )
    for pattern in patterns:
        values.extend(re.findall(pattern, raw))

    out: List[str] = []
    for value in values:
        candidate = str(value or "").strip().strip(" \t\r\n\"'()[]{}<>,.;")
        if not candidate:
            continue
        if not candidate.startswith(("http://", "https://")):
            candidate = "https://" + candidate
        if not thin._safe_http_url(candidate):
            continue
        if not base._same_org_host(start_url, candidate):
            continue
        if candidate not in out:
            out.append(candidate)
    return out


''')
if "def _dart_auxiliary_official_candidates(" not in text:
    text = text.replace(crawl_marker, helper + crawl_marker, 1)

insertion_marker = "    first_party = thin._first_party_bootstrap_candidates(http, start_url, original_pages)\n"
if insertion_marker not in text:
    raise SystemExit("first-party marker not found; refusing fuzzy patch")

insertion = textwrap.dedent(r'''
    # Before broad search, try additional official URLs that DART itself
    # publishes for the same legal entity (for example an IR Website). These
    # remain inside the DART-anchored organization boundary and are accepted only
    # when their fetched navigation is strictly better than the thin primary surface.
    dart_auxiliary = _dart_auxiliary_official_candidates(http, start_url, company)
    recovery.last_recovery["stages_attempted"].append({
        "stage": "DART_AUXILIARY_OFFICIAL",
        "candidate_count": len(dart_auxiliary),
        "sample_candidates": dart_auxiliary[:10],
    })
    resolved = _try_candidates(
        http, start_url, company, dart_auxiliary, original_evidence,
        "DART_AUXILIARY_OFFICIAL", max_pages, deadline,
    )
    if resolved:
        return resolved
    if _deadline_exceeded(deadline):
        _mark_runtime_guard("DART_AUXILIARY_OFFICIAL", deadline)
        return (original_pages, original_links) if original_pages else ([], [])

''')
# dedent removed the function-body indentation; restore it deterministically.
insertion = "".join(("    " + line if line.strip() else line) for line in insertion.splitlines(keepends=True))
if '"stage": "DART_AUXILIARY_OFFICIAL"' not in text:
    text = text.replace(insertion_marker, insertion + insertion_marker, 1)
code_path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_g0_staged_official_recovery.py")
tests = test_path.read_text(encoding="utf-8")
end_marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
if end_marker not in tests:
    raise SystemExit("test end marker not found; refusing fuzzy patch")

test_block = textwrap.dedent(r'''
    def test_dart_auxiliary_official_seed_recovers_thin_primary_before_search(self):
        start = "https://www.example-corp.com/"
        ir_url = "https://www.example-corp.com/en/ir/activity"
        shell = Page(start, "login", "<html></html>", 200)
        deep_pages = [
            Page(ir_url, "Example Corp company business sustainability copyright", "", 200),
            Page("https://www.example-corp.com/company/location", "Example Corp location", "", 200),
        ]
        deep_links = [
            (ir_url, "Company", "https://www.example-corp.com/company/about"),
            (ir_url, "Location", "https://www.example-corp.com/company/location"),
            (ir_url, "Sustainability", "https://www.example-corp.com/sustainability"),
        ]

        def crawl(_http, url, max_pages, deadline=None):
            if url == start:
                return [shell], []
            if url == ir_url:
                return deep_pages, deep_links
            raise AssertionError(f"unexpected crawl: {url}")

        legal = {
            "korean_name": "Example Corp",
            "website": "www.example-corp.com",
            "raw_text": "Company Information Website www.example-corp.com IR Website www.example-corp.com/en/ir/activity Telephone 00-0000-0000",
        }
        with patch.object(staged, "_crawl_no_search", side_effect=crawl), \
             patch.object(staged.base, "resolve_legal_identity", return_value=(legal, [legal])), \
             patch.object(thin, "_first_party_bootstrap_candidates", side_effect=AssertionError("bootstrap must be skipped after DART auxiliary recovery")), \
             patch.object(thin, "_anchored_domain_candidates", side_effect=AssertionError("search must be skipped after DART auxiliary recovery")), \
             patch.object(recovery, "_locate_candidates", side_effect=AssertionError("replacement must be skipped after DART auxiliary recovery")):
            pages, _ = staged.crawl_official(object(), start, "Example Corp")

        self.assertEqual(pages[0].url, ir_url)
        self.assertEqual(recovery.last_recovery["successful_stage"], "DART_AUXILIARY_OFFICIAL")
        self.assertEqual(
            recovery.last_recovery["method"],
            "DART_HOST_DART_AUXILIARY_OFFICIAL",
        )

    def test_dart_auxiliary_official_seed_rejects_cross_org_url(self):
        legal = {
            "raw_text": "IR Website https://unrelated.example.net/investors",
        }
        with patch.object(staged.base, "resolve_legal_identity", return_value=(legal, [legal])):
            candidates = staged._dart_auxiliary_official_candidates(
                object(), "https://www.example-corp.com/", "Example Corp"
            )
        self.assertEqual(candidates, [])
''')
# Methods belong inside the existing TestCase class.
test_block = "".join(("    " + line if line.strip() else line) for line in test_block.splitlines(keepends=True))
if "test_dart_auxiliary_official_seed_recovers_thin_primary_before_search" not in tests:
    tests = tests.replace(end_marker, "\n" + test_block + end_marker, 1)
test_path.write_text(tests, encoding="utf-8")
