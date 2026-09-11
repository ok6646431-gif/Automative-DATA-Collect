import csv
import json
import tempfile
import unittest
from pathlib import Path

from cross_entity_attachment_scope import match_envinfo_attachment
from archive_builder import build_envinfo_user, promote_envinfo_references
from scope_quality import classify_archive_summary


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def valid_pdf_bytes(label: bytes) -> bytes:
    return b'%PDF-1.4\n' + label + b'\n' + b'0' * 1200 + b'\n%%EOF'


class CrossEntityAttachmentScopeTests(unittest.TestCase):
    def scope(self):
        return {
            'excluded_source_ids': [
                {
                    'source_key':'ENVINFO',
                    'source_site_id':'HOLD-1',
                    'source_site_name_raw':'알파홀딩스 주식회사',
                    'reason':'SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY',
                },
                {
                    'source_key':'ENVINFO',
                    'source_site_id':'SHORT',
                    'source_site_name_raw':'ABC',
                    'reason':'SOURCE_ENTITY_NAME_NOT_CURRENT_COMPANY',
                },
                {
                    'source_key':'PRTR',
                    'source_site_id':'OTHER',
                    'source_site_name_raw':'베타홀딩스 주식회사',
                    'reason':'SOURCE_ENTITY_NAME_NOT_CURRENT_COMPANY',
                },
            ]
        }

    def test_explicit_verified_excluded_entity_in_filename_is_blocked(self):
        decision=match_envinfo_attachment(
            {'original_filename':'2024 알파홀딩스 지속가능경영보고서.pdf'}, self.scope()
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision['decision'],'CROSS_ENTITY_ATTACHMENT_EXCLUDED')
        self.assertEqual(decision['matched_excluded_source_id'],'HOLD-1')

    def test_legitimate_or_short_generic_names_are_not_blocked(self):
        self.assertIsNone(match_envinfo_attachment(
            {'original_filename':'2024 알파 지속가능경영보고서.pdf'}, self.scope()
        ))
        self.assertIsNone(match_envinfo_attachment(
            {'original_filename':'ABC 환경관리자료.pdf'}, self.scope()
        ))
        self.assertIsNone(match_envinfo_attachment(
            {'original_filename':'베타홀딩스 환경보고서.pdf'}, self.scope()
        ))

    def test_archive_user_layer_excludes_cross_entity_attachment_but_preserves_source_raw(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)/'package'; archive=Path(td)/'archive'
            env=package/'output'/'ENVINFO'; raw=env/'raw_attachments'/'2024'/'SITE-A'
            raw.mkdir(parents=True); archive.mkdir()
            (package/'Company_Profile.json').write_text(json.dumps({'company_display_name':'알파주식회사'}),encoding='utf-8')
            (package/'Requested_Scope.json').write_text(json.dumps(self.scope(),ensure_ascii=False),encoding='utf-8')
            foreign=raw/'foreign.pdf'; foreign.write_bytes(valid_pdf_bytes(b'foreign'))
            local=raw/'local.pdf'; local.write_bytes(valid_pdf_bytes(b'local'))
            write_csv(env/'discovery.csv',[])
            rows=[
                {'year':'2024','compId':'SITE-A','compNm':'알파공장','file_id':'F1','original_filename':'2024 알파홀딩스 지속가능경영보고서.pdf','stored_path':str(foreign.relative_to(package)),'collection_status':'DOWNLOADED','sha256':'foreign','section_id':'inquiry26','section_title':'환경(지속가능)보고서 발간 현황','document_category':'OTHER_ENVINFO_EVIDENCE'},
                {'year':'2024','compId':'SITE-A','compNm':'알파공장','file_id':'F2','original_filename':'알파공장 환경방침.pdf','stored_path':str(local.relative_to(package)),'collection_status':'DOWNLOADED','sha256':'local','section_id':'inquiry03','section_title':'녹색경영 방침','document_category':'ENV_POLICY_GOAL'},
            ]
            write_csv(env/'attachment_index.csv',rows)
            created,failures,excluded=build_envinfo_user(package,archive,{'ENVINFO':{'SITE-A'}},{})
            self.assertEqual(failures,[])
            self.assertEqual(len(excluded),1)
            self.assertEqual(excluded[0]['original_filename'],'2024 알파홀딩스 지속가능경영보고서.pdf')
            self.assertTrue(foreign.exists(),'raw source must be preserved')
            self.assertFalse(any('알파홀딩스' in p.name for p in created))
            self.assertTrue(any('환경방침' in p.name for p in created))
            promoted=promote_envinfo_references(package,archive,{'ENVINFO':{'SITE-A'}},'알파주식회사')
            self.assertFalse(any('알파홀딩스' in p.name for p in promoted))

    def test_verified_annual_coverage_supersedes_legacy_physical_minimum(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'Collection_Completeness.json').write_text(json.dumps({'status':'COMPLETE'}),encoding='utf-8')
            summary={'acceptance_checks':{
                'sustainability_minimum_5':False,
                'sustainability_coverage_sufficient':True,
                'user_excel_exports':True,
                'guideline_reference_present':False,
            }}
            result=classify_archive_summary(root,summary)
            self.assertEqual(result['archive_completeness'],'COMPLETE')
            self.assertFalse(result['acceptance_checks']['sustainability_minimum_5'])
            self.assertNotIn('sustainability_minimum_5',result['blocking_acceptance_checks'])

    def test_legacy_minimum_stays_blocking_without_coverage_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'Collection_Completeness.json').write_text(json.dumps({'status':'COMPLETE'}),encoding='utf-8')
            result=classify_archive_summary(root,{'acceptance_checks':{'sustainability_minimum_5':False}})
            self.assertEqual(result['archive_completeness'],'INCOMPLETE')
            self.assertIn('sustainability_minimum_5',result['blocking_acceptance_checks'])


if __name__=='__main__':
    unittest.main()