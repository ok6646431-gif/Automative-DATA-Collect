import unittest

from orchestrator import g0_official_site_recovery as recovery


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


if __name__ == "__main__":
    unittest.main()
