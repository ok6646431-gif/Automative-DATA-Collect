import unittest
from unittest.mock import patch

from orchestrator import g0_official_site_recovery as recovery
from orchestrator import g0_thin_shell_recovery as thin
from orchestrator.zero_touch_discovery import Page


class OfficialSiteRecoverySearchParsingTests(unittest.TestCase):
    def test_extracts_displayed_and_embedded_destinations(self):
        html = r'''
        <html><body>
          <a href="https://www.google.com/url?q=https%3A%2F%2Ftracker.invalid%2F">tracking</a>
          <div data-url="https://www.example-corp.com/company/about">about</div>
          <cite>www.example-corp.com</cite>
          <script>{"destination":"https:\/\/www.example-corp.com\/sustainability\/report"}</script>
        </body></html>
        '''
        links = recovery._search_result_links("https://www.google.com/search?q=example", html)
        self.assertIn("https://www.example-corp.com/company/about", links)
        self.assertIn("https://www.example-corp.com", links)
        self.assertIn("https://www.example-corp.com/sustainability/report", links)

    def test_blocks_search_engine_and_other_untrusted_locator_hosts_only_at_locator_stage(self):
        html = r'''
        <html><body>
          <cite>https://www.bing.com/ck/a?x=1</cite>
          <cite>https://www.google.com/search?q=corp</cite>
          <cite>https://www.example-corp.com/company</cite>
        </body></html>
        '''
        links = recovery._search_result_links("https://www.bing.com/search?q=corp", html)
        self.assertEqual(["https://www.example-corp.com/company"], links)

    def test_bare_www_candidate_is_normalized_to_https(self):
        links = recovery._search_result_links(
            "https://www.google.com/search?q=corp",
            "Official site: www.example-corp.com/about",
        )
        self.assertEqual(["https://www.example-corp.com/about"], links)


class ThinShellRecoveryTests(unittest.TestCase):
    def test_http_200_zero_navigation_shell_recovers_deep_path_on_dart_host(self):
        start = "https://www.example-corp.com/"
        thin_page = Page(start, "Example Corp", "<html><body>Example Corp</body></html>", 200)
        deep = "https://www.example-corp.com/company/about"
        deep_pages = [
            Page(deep, "Example Corp 회사소개 사업분야 지속가능 투자자 copyright", "", 200),
            Page("https://www.example-corp.com/company/location", "Example Corp 사업장", "", 200),
        ]
        deep_links = [
            (deep, "회사소개", "https://www.example-corp.com/company/about"),
            (deep, "사업장", "https://www.example-corp.com/company/location"),
            (deep, "ESG", "https://www.example-corp.com/sustainability"),
            (deep, "IR", "https://www.example-corp.com/investor"),
            (deep, "채용", "https://www.example-corp.com/career"),
        ]

        def base_crawl(_http, url, _company, max_pages=90):
            if url == deep:
                return deep_pages, deep_links
            return [thin_page], []

        with patch.object(recovery, "crawl_official", return_value=([thin_page], [])), \
             patch.object(recovery, "BASE_CRAWL", side_effect=base_crawl), \
             patch.object(thin, "_anchored_domain_candidates", return_value=[deep]), \
             patch.object(thin, "_embedded_candidates", return_value=[]), \
             patch.object(recovery, "_locate_candidates", return_value=[]):
            pages, links = thin.crawl_official(object(), start, "Example Corp")

        self.assertEqual(pages[0].url, deep)
        self.assertEqual(links, deep_links)
        self.assertEqual(recovery.last_recovery["status"], "RECOVERED")
        self.assertEqual(recovery.last_recovery["method"], "DART_HOST_DEEP_PATH")

    def test_unresolved_thin_shell_preserves_original_first_party_page(self):
        start = "https://www.example-corp.com/"
        page = Page(start, "Example Corp", "<html></html>", 200)
        with patch.object(recovery, "crawl_official", return_value=([page], [])), \
             patch.object(thin, "_anchored_domain_candidates", return_value=[]), \
             patch.object(thin, "_embedded_candidates", return_value=[]), \
             patch.object(recovery, "_locate_candidates", return_value=[]):
            pages, links = thin.crawl_official(object(), start, "Example Corp")

        self.assertEqual(pages, [page])
        self.assertEqual(links, [])
        self.assertEqual(recovery.last_recovery["status"], "THIN_SURFACE_UNRESOLVED")

    def test_static_redirect_candidate_must_stay_in_same_organization(self):
        start = "https://www.example-corp.com/"
        page = Page(
            start,
            "Example Corp",
            """<html><head><meta http-equiv='refresh' content='0; url=/company/'></head>
            <script>window.location='https://attacker.example.net/company/'</script></html>""",
            200,
        )
        candidates = thin._embedded_candidates(start, [page])
        self.assertIn("https://www.example-corp.com/company/", candidates)
        self.assertNotIn("https://attacker.example.net/company/", candidates)


if __name__ == "__main__":
    unittest.main()
