import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator.brefos_byte_registry import _choose_discovery, _select_documents


class BREFOSByteRegistryFallbackTests(unittest.TestCase):
    @staticmethod
    def _snapshot(checked_at=None):
        return {
            'status':'PASS',
            'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
            'source_url':'https://ieps.nier.go.kr/brefos/home/board/standardDoc/list.do',
            'advertised_total_records':2,
            'discovered_document_count':2,
            'documents':[
                {'atch_file_id':'10','title':'A','viewer_pdf_url':'https://example.invalid/10.pdf'},
                {'atch_file_id':'20','title':'B','viewer_pdf_url':'https://example.invalid/20.pdf'},
            ],
        }

    def _write_snapshot(self, root: Path, payload):
        p=root/'snapshot.json'
        p.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        return p

    def test_live_pass_always_wins_over_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            p=self._write_snapshot(Path(td),self._snapshot())
            live={'status':'PASS','documents':[{'atch_file_id':'LIVE'}],'discovered_document_count':1}
            chosen,basis=_choose_discovery(live,p,14)
        self.assertIs(chosen,live)
        self.assertEqual(basis['basis'],'LIVE_BREFOS_DISCOVERY')
        self.assertFalse(basis['snapshot_used'])

    def test_source_unreachable_uses_fresh_last_verified_snapshot(self):
        snapshot=self._snapshot()
        with tempfile.TemporaryDirectory() as td:
            p=self._write_snapshot(Path(td),snapshot)
            chosen,basis=_choose_discovery({'status':'SOURCE_UNREACHABLE'},p,14)
        self.assertEqual(chosen['documents'],snapshot['documents'])
        self.assertEqual(basis['basis'],'LAST_VERIFIED_SNAPSHOT_FALLBACK')
        self.assertTrue(basis['snapshot_used'])

    def test_stale_snapshot_is_rejected(self):
        stale=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
        with tempfile.TemporaryDirectory() as td:
            p=self._write_snapshot(Path(td),self._snapshot(stale))
            live={'status':'SOURCE_UNREACHABLE'}
            chosen,basis=_choose_discovery(live,p,14)
        self.assertIs(chosen,live)
        self.assertEqual(basis['basis'],'SNAPSHOT_REJECTED')
        self.assertFalse(basis['snapshot_used'])

    def test_live_parse_or_content_failure_never_uses_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            p=self._write_snapshot(Path(td),self._snapshot())
            live={'status':'COUNT_MISMATCH','documents':[{'atch_file_id':'LIVE_BAD'}]}
            chosen,basis=_choose_discovery(live,p,14)
        self.assertIs(chosen,live)
        self.assertEqual(basis['basis'],'LIVE_BREFOS_DISCOVERY_FAILED_CLOSED')
        self.assertFalse(basis['snapshot_used'])

    def test_target_selection_reports_missing_id_and_preserves_order(self):
        docs=self._snapshot()['documents']
        selected,missing=_select_documents(docs,['20','30','10'])
        self.assertEqual([d['atch_file_id'] for d in selected],['10','20'])
        self.assertEqual(missing,['30'])

    def test_empty_target_selects_full_snapshot(self):
        docs=self._snapshot()['documents']
        selected,missing=_select_documents(docs,[])
        self.assertEqual(selected,docs)
        self.assertEqual(missing,[])


if __name__=='__main__': unittest.main()
