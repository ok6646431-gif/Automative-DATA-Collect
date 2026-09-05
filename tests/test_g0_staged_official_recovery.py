import unittest
from unittest.mock import patch

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import g0_staged_official_recovery as staged
from orchestrator import g0_thin_shell_recovery as thin
from orchestrator.zero_touch_discovery import Page


class StagedOfficialRecoveryTests(unittest.TestCase):
    def test_first_party_success_skips_search_fallbacks(self):
        start = "https://www.example-corp.com/"
        shell = Page(start, "", "<html></html>", 200)
        deep = "https://www.example-corp.com/company/about"
        pages = [
            Page(deep, "Example Corp 회사소개 사업분야 지속가능 copyright", "", 200),
            Page("https://www.example-corp.com/company/location", "Example Corp 사업장", "", 200),
        ]
        links = [
            (deep, "회사소개", deep),
            (deep, "사업장", "https://www.example-corp.com/company/location"),
            (deep, "ESG", "https://www.example-corp.com/sustainability"),
        ]

        def crawl(_http, url, max_pages):
            if url == start:
                return [shell], []
            return pages, links

        with patch.object(staged, "_crawl_no_search", side_effect=crawl), \
             patch.object(thin, "_first_party_bootstrap_candidates", return_value=[deep]), \
             patch.object(thin, "_anchored_domain_candidates", side_effect=AssertionError("search fallback must be skipped")), \
             patch.object(recovery, "_locate_candidates", side_effect=AssertionError("replacement fallback must be skipped")):
            resolved_pages, _ = staged.crawl_official(object(), start, "Example Corp")

        self.assertEqual(resolved_pages[0].url, deep)
        self.assertEqual(recovery.last_recovery["successful_stage"], "FIRST_PARTY_BOOTSTRAP")
        self.assertEqual(recovery.last_recovery["method"], "DART_HOST_FIRST_PARTY_BOOTSTRAP")

    def test_search_fallback_runs_only_after_first_party_candidates_fail(self):
        start = "https://www.example-corp.com/"
        shell = Page(start, "", "<html></html>", 200)
        weak = "https://www.example-corp.com/empty"
        deep = "https://www.example-corp.com/company/about"
        strong_pages = [
            Page(deep, "Example Corp 회사소개 사업분야 지속가능 copyright", "", 200),
            Page("https://www.example-corp.com/company/location", "Example Corp 사업장", "", 200),
        ]
        strong_links = [(deep, "사업장", "https://www.example-corp.com/company/location")]

        def crawl(_http, url, max_pages):
            if url in {start, weak}:
                return [shell], []
            return strong_pages, strong_links

        with patch.object(staged, "_crawl_no_search", side_effect=crawl), \
             patch.object(thin, "_first_party_bootstrap_candidates", return_value=[weak]), \
             patch.object(thin, "_anchored_domain_candidates", return_value=[deep]), \
             patch.object(recovery, "_locate_candidates", return_value=[]):
            resolved_pages, _ = staged.crawl_official(object(), start, "Example Corp")

        self.assertEqual(resolved_pages[0].url, deep)
        self.assertEqual(recovery.last_recovery["successful_stage"], "ANCHORED_SEARCH")

    def test_candidate_validation_uses_probe_budget_not_full_discovery_budget(self):
        start = "https://www.example-corp.com/"
        shell = Page(start, "", "<html></html>", 200)
        deep = "https://www.example-corp.com/company/about"
        pages = [
            Page(deep, "Example Corp 회사소개 사업분야 지속가능 copyright", "", 200),
            Page("https://www.example-corp.com/company/location", "Example Corp 사업장", "", 200),
        ]
        links = [(deep, "사업장", "https://www.example-corp.com/company/location")]
        budgets = []

        def crawl(_http, url, max_pages):
            if url == start:
                return [shell], []
            budgets.append(max_pages)
            return pages, links

        with patch.object(staged, "_crawl_no_search", side_effect=crawl), \
             patch.object(thin, "_first_party_bootstrap_candidates", return_value=[deep]), \
             patch.object(thin, "_anchored_domain_candidates", side_effect=AssertionError("search fallback must be skipped")), \
             patch.object(recovery, "_locate_candidates", side_effect=AssertionError("replacement fallback must be skipped")):
            staged.crawl_official(object(), start, "Example Corp", max_pages=90)

        self.assertEqual(budgets, [staged.MAX_CANDIDATE_PROBE_PAGES])
        self.assertLess(staged.MAX_CANDIDATE_PROBE_PAGES, 90)
        self.assertEqual(
            recovery.last_recovery["candidate_probe_page_budget"],
            staged.MAX_CANDIDATE_PROBE_PAGES,
        )

    def test_initial_dart_surface_does_not_call_legacy_search_seeding_crawler(self):
        start = "https://www.example-corp.com/"
        page = Page(start, "Example Corp 회사소개 지속가능 copyright", "", 200)
        links = [
            (start, "회사소개", "https://www.example-corp.com/company"),
            (start, "사업장", "https://www.example-corp.com/location"),
            (start, "ESG", "https://www.example-corp.com/sustainability"),
        ]
        with patch.object(staged, "_crawl_no_search", return_value=([page, page], links)), \
             patch.object(recovery, "crawl_official", side_effect=AssertionError("legacy crawler must not run")), \
             patch.object(thin, "_first_party_bootstrap_candidates", side_effect=AssertionError("bootstrap not needed")):
            pages, resolved_links = staged.crawl_official(object(), start, "Example Corp")

        self.assertEqual(len(pages), 2)
        self.assertEqual(resolved_links, links)


if __name__ == "__main__":
    unittest.main()
