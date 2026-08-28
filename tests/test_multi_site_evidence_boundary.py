import sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))
from cross_layer_review import compatible


class TestMultiSiteEvidenceBoundary(unittest.TestCase):
    def test_specific_site_evidence_does_not_satisfy_multi_site_topic(self):
        topic={'canonical_site_id':'MULTI_SITE','domain':'CHEMICALS'}
        evidence={'canonical_site_id':'SITE_A','domain':'CHEMICALS'}
        self.assertFalse(compatible(topic,evidence))

    def test_company_wide_or_explicit_multi_site_evidence_can_match_multi_site_topic(self):
        topic={'canonical_site_id':'MULTI_SITE','domain':'CHEMICALS'}
        self.assertTrue(compatible(topic,{'canonical_site_id':'','domain':'CHEMICALS'}))
        self.assertTrue(compatible(topic,{'canonical_site_id':'MULTI_SITE','domain':'CHEMICALS'}))

    def test_multi_site_evidence_does_not_satisfy_specific_site_topic(self):
        topic={'canonical_site_id':'SITE_A','domain':'CHEMICALS'}
        evidence={'canonical_site_id':'MULTI_SITE','domain':'CHEMICALS'}
        self.assertFalse(compatible(topic,evidence))

    def test_cross_media_reference_still_respects_site_boundary(self):
        energy_topic={'canonical_site_id':'SITE_ENERGY','domain':'AIR'}
        other_topic={'canonical_site_id':'SITE_CHEM','domain':'AIR'}
        ref={'canonical_site_id':'SITE_ENERGY','domain':'CROSS_MEDIA'}
        self.assertTrue(compatible(energy_topic,ref))
        self.assertFalse(compatible(other_topic,ref))


if __name__=='__main__': unittest.main()
