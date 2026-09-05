import unittest

from orchestrator.brefos_catalog_discovery import parse_page


SAMPLE='''
<html><body>
<table><tr><td>211</td><td>
<a href="#" onclick="fn_docView(1501,'BBS_2025122315043330','211');">보기</a>
<a href="#" onclick="fn_zipDown('1501','[2기] 반도체 제조업 기준서');">다운로드</a>
</td></tr></table>
<script>new pagingView("1", "35", "10");</script>
</body></html>
'''


class BREFOSCatalogDiscoveryTests(unittest.TestCase):
    def test_parse_stable_ids_and_title(self):
        d=parse_page(SAMPLE,1)
        self.assertEqual(d['page_document_count'],1)
        row=d['documents'][0]
        self.assertEqual(row['atch_file_id'],'1501')
        self.assertEqual(row['stdrdoc_origin_id'],'BBS_2025122315043330')
        self.assertEqual(row['ntt_id'],'211')
        self.assertEqual(row['title'],'[2기] 반도체 제조업 기준서')
        self.assertTrue(row['viewer_pdf_url'].endswith('atchFileId=1501'))

    def test_parse_paging_contract(self):
        d=parse_page(SAMPLE,1)
        self.assertEqual(d['paging']['total_records'],35)
        self.assertEqual(d['paging']['records_per_page'],10)
        self.assertEqual(d['paging']['total_pages'],4)


if __name__=='__main__': unittest.main()
