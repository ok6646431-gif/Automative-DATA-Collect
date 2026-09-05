import unittest

from orchestrator.brefos_catalog_promote import build_candidate


class BREFOSCatalogPromoteTests(unittest.TestCase):
    @staticmethod
    def master(single=True):
        entry={
            'catalog_id':'BAT_CURRENT','catalog_family':'FAM','preferred':True,
            'publication_status':'PUBLISHED','collection_policy':'WAIT_FOR_LATEST_LOCATOR',
            'title':'테스트 기준서','official_pdf_url':'','official_pdf_sha256':'','notes':'',
        }
        return {'schema_version':'test','catalog_as_of':'old','discovery':{},'entries':[entry]}

    @staticmethod
    def registry(ids, status='PASS'):
        return {
            'status':status,'selection_mode':'ATCH_FILE_ID_SET','selected_document_count':len(ids),
            'verified_pdf_count':len(ids) if status=='PASS' else max(0,len(ids)-1),
            'discovered_document_count':35,'documents':[
                {'atch_file_id':str(i),'ntt_id':str(100+i),'title':f'part {i}','viewer_pdf_url':f'https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId={i}','status':'VERIFIED_PDF','bytes':1000+i,'sha256':format(i,'064x')}
                for i in ids
            ],
        }

    @staticmethod
    def reconcile(ids):
        return {'master_matches':[
            {'catalog_id':'BAT_CURRENT','match_state':'AUTO_MATCH','matched_documents':[
                {'atch_file_id':str(i),'ntt_id':str(100+i),'title':f'part {i}'} for i in ids
            ]}
        ]}

    def test_partial_targeted_registry_blocks_every_promotion(self):
        registry=self.registry([1,2,3,4],status='PARTIAL')
        candidate,report=build_candidate(self.master(),registry,self.reconcile([1,2,3,4]))
        self.assertEqual(report['status'],'BLOCKED')
        self.assertEqual(report['promoted'],[])
        self.assertEqual(candidate['entries'][0]['collection_policy'],'WAIT_FOR_LATEST_LOCATOR')

    def test_complete_four_part_revision_promotes_as_official_documents(self):
        candidate,report=build_candidate(self.master(),self.registry([1,2,3,4]),self.reconcile([1,2,3,4]))
        self.assertEqual(report['status'],'PASS',report['blocked'])
        entry=candidate['entries'][0]
        self.assertEqual(entry['collection_policy'],'COLLECT_WHEN_MATCHED')
        self.assertEqual(len(entry['official_documents']),4)
        self.assertEqual({d['atch_file_id'] for d in entry['official_documents']},{'1','2','3','4'})
        self.assertTrue(all(len(d['official_pdf_sha256'])==64 for d in entry['official_documents']))
        self.assertEqual(entry['official_pdf_url'],'')

    def test_single_verified_document_promotes_to_legacy_single_fields(self):
        candidate,report=build_candidate(self.master(),self.registry([9]),self.reconcile([9]))
        self.assertEqual(report['status'],'PASS')
        entry=candidate['entries'][0]
        self.assertIn('atchFileId=9',entry['official_pdf_url'])
        self.assertEqual(len(entry['official_pdf_sha256']),64)
        self.assertNotIn('official_documents',entry)

    def test_existing_conflicting_sha_blocks_overwrite(self):
        master=self.master(); master['entries'][0]['official_pdf_url']='https://ieps.nier.go.kr/brefos/common/file/pdfDocPdf.do?atchFileId=9'; master['entries'][0]['official_pdf_sha256']='f'*64
        _,report=build_candidate(master,self.registry([9]),self.reconcile([9]))
        self.assertEqual(report['status'],'BLOCKED')
        self.assertEqual(report['blocked'][0]['reason'],'EXISTING_SINGLE_DOCUMENT_CONFLICT')


if __name__=='__main__': unittest.main()
