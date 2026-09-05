import unittest

from orchestrator.bat_catalog_hydration import select_entries


class BATCatalogHydrationTests(unittest.TestCase):
    @staticmethod
    def _entry(catalog_id, *, preferred=True, status='PUBLISHED', policy='WAIT_FOR_LATEST_LOCATOR', sha=''):
        return {
            'catalog_id':catalog_id,
            'preferred':preferred,
            'publication_status':status,
            'collection_policy':policy,
            'official_pdf_sha256':sha,
        }

    def test_locator_pending_selects_only_published_preferred_waiting_entries(self):
        catalog={'entries':[
            self._entry('A'),
            self._entry('B',preferred=False),
            self._entry('C',status='UNDER_DEVELOPMENT'),
            self._entry('D',policy='COLLECT_WHEN_MATCHED'),
        ]}
        self.assertEqual([x['catalog_id'] for x in select_entries(catalog,'locator-pending')], ['A'])

    def test_unverified_published_selects_missing_hash_across_policies(self):
        catalog={'entries':[
            self._entry('A'),
            self._entry('B',policy='COLLECT_WHEN_MATCHED'),
            self._entry('C',policy='COLLECT_WHEN_MATCHED',sha='a'*64),
            self._entry('D',status='UNDER_DEVELOPMENT'),
        ]}
        self.assertEqual({x['catalog_id'] for x in select_entries(catalog,'unverified-published')}, {'A','B'})


if __name__=='__main__': unittest.main()
