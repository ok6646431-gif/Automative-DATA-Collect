import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'orchestrator'))

from bat_legal_applicability import annotate


class BATLegalApplicabilityTests(unittest.TestCase):
    def _seed_candidates(self, root, rows):
        fields = [
            'candidate_id','catalog_id','catalog_family','revision_generation','canonical_site_id','site_name',
            'candidate_role','candidate_state','applicability_state','publication_status','legal_status','effective_from',
            'matched_ksic_prefixes','matched_industry_terms','matched_process_terms','matched_utility_terms',
            'evidence_channels','evidence_basis','collection_action','official_source_locator'
        ]
        with (root / 'BAT_Applicability_Candidates.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader(); w.writerows(rows)

    def test_non_target_is_explicit_and_still_keeps_technical_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = {
                'candidate_id':'BATMAP_X_SITE1','catalog_id':'BAT_X','catalog_family':'X','revision_generation':'2',
                'canonical_site_id':'SITE1','site_name':'테스트공장','candidate_role':'PRIMARY',
                'candidate_state':'PRIMARY_CANDIDATE','applicability_state':'STRONG_CANDIDATE',
                'publication_status':'PUBLISHED','legal_status':'CURRENT','effective_from':'',
                'matched_ksic_prefixes':'20','matched_industry_terms':'화학','matched_process_terms':'',
                'matched_utility_terms':'','evidence_channels':'ENVINFO','evidence_basis':'industry=화학',
                'collection_action':'COLLECT','official_source_locator':'https://example.invalid/bat.pdf'
            }
            self._seed_candidates(root, [row])
            (root / 'Integrated_Environmental_Management_Applicability.json').write_text(json.dumps({
                'sites':[{
                    'canonical_site_id':'SITE1',
                    'legal_applicability_state':'NON_TARGET_CONFIRMED',
                    'source_locator':'https://official.example/non-target',
                }]
            }, ensure_ascii=False), encoding='utf-8')
            plan, boundary = annotate(root, {'candidates':[dict(row)], 'boundaries':[]})
            candidate = plan['candidates'][0]
            self.assertEqual('NON_TARGET_CONFIRMED', candidate['site_legal_applicability_state'])
            self.assertEqual('STRONG', candidate['technical_relevance_state'])
            self.assertEqual('NOT_VERIFIED', candidate['company_adoption_state'])
            self.assertEqual('TECHNICAL_REFERENCE_ONLY', candidate['bat_reference_use'])
            self.assertEqual('COLLECT', candidate['collection_action'])
            self.assertEqual({'NON_TARGET_CONFIRMED': 1}, boundary['site_legal_applicability_counts'])

    def test_absence_never_becomes_non_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = {
                'candidate_id':'BATMAP_X_SITE1','catalog_id':'BAT_X','catalog_family':'X','revision_generation':'2',
                'canonical_site_id':'SITE1','site_name':'테스트공장','candidate_role':'SECONDARY_PROCESS',
                'candidate_state':'TECHNICAL_CANDIDATE','applicability_state':'SUPPORTING_CANDIDATE',
                'publication_status':'PUBLISHED','legal_status':'CURRENT','effective_from':'',
                'matched_ksic_prefixes':'','matched_industry_terms':'','matched_process_terms':'세정',
                'matched_utility_terms':'','evidence_channels':'ENVINFO','evidence_basis':'process=세정',
                'collection_action':'REVIEW_BEFORE_COLLECTION','official_source_locator':'https://example.invalid/bat.pdf'
            }
            self._seed_candidates(root, [row])
            plan, _ = annotate(root, {'candidates':[dict(row)], 'boundaries':[]})
            candidate = plan['candidates'][0]
            self.assertEqual('UNKNOWN', candidate['site_legal_applicability_state'])
            self.assertEqual('TECHNICAL_REFERENCE_PENDING_LEGAL_SCOPE', candidate['bat_reference_use'])

    def test_verified_ieps_document_can_confirm_target_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = {
                'candidate_id':'BATMAP_X_SITE1','catalog_id':'BAT_X','catalog_family':'X','revision_generation':'2',
                'canonical_site_id':'SITE1','site_name':'테스트공장','candidate_role':'PRIMARY',
                'candidate_state':'PRIMARY_CANDIDATE','applicability_state':'STRONG_CANDIDATE',
                'publication_status':'PUBLISHED','legal_status':'CURRENT','effective_from':'',
                'matched_ksic_prefixes':'','matched_industry_terms':'화학','matched_process_terms':'',
                'matched_utility_terms':'','evidence_channels':'ENVINFO','evidence_basis':'industry=화학',
                'collection_action':'COLLECT','official_source_locator':'https://example.invalid/bat.pdf'
            }
            self._seed_candidates(root, [row])
            out = root / 'output' / 'CORP_DOCS'
            out.mkdir(parents=True)
            fields = ['canonical_site_id','site_name_raw','verification_status','collection_status','source_locator','source_url','title','notes','original_filename']
            with (out / 'document_index.csv').open('w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerow({
                    'canonical_site_id':'SITE1','site_name_raw':'테스트공장','verification_status':'SOURCE_VERIFIED',
                    'collection_status':'DOWNLOADED','source_locator':'https://ieps.nier.go.kr/web/board/7/1001/',
                    'source_url':'https://ieps.nier.go.kr/file.pdf','title':'통합환경허가 정보공개','notes':'',
                    'original_filename':'통합환경허가 검토결과서.pdf'
                })
            plan, _ = annotate(root, {'candidates':[dict(row)], 'boundaries':[]})
            self.assertEqual('TARGET_CONFIRMED', plan['candidates'][0]['site_legal_applicability_state'])
            self.assertEqual('LEGAL_AND_TECHNICAL_CONTEXT', plan['candidates'][0]['bat_reference_use'])


if __name__ == '__main__':
    unittest.main()
