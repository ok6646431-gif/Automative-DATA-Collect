import sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'orchestrator'))

from topic_semantic_bridge import evaluate_semantic_bridge


def ev(eid,title,statement,domain):
    return {'evidence_id':eid,'title':title,'statement':statement,'domain':domain}


class TopicSemanticBridgeTests(unittest.TestCase):
    def test_nox_scr_chain_is_ready(self):
        result=evaluate_semantic_bridge(
            {'domain':'AIR'},
            [ev('O1','NOx','LEVEL_SHIFT_CANDIDATE','AIR')],
            [ev('A1','SCR 구축','보일러 NOx 배출량 저감을 위한 SCR 구축','AIR')],
            [ev('I1','K-BREF','질소산화물(NOx) 저감을 위한 SCR 및 SNCR 기술','AIR')],
            [ev('F1','대기 목표','대기오염물질 배출 목표 수립 및 관리','AIR')],
        )
        self.assertEqual(result['state'],'READY')
        self.assertEqual(result['anchors'],['NOX'])
        self.assertEqual(result['action_evidence_ids'],['A1'])

    def test_dust_action_does_not_bridge_nox_sox_topic(self):
        result=evaluate_semantic_bridge(
            {'domain':'AIR'},
            [ev('O1','NOx','LEVEL_SHIFT','AIR'),ev('O2','SOx','LEVEL_SHIFT','AIR')],
            [ev('A1','요소수 제조공정 방지시설','암모니아 및 먼지 저감을 위한 흡수시설 설치','AIR')],
            [ev('I1','K-BREF','NOx 및 SOx 저감을 위한 탈질·탈황 기술','AIR')],
            [ev('F1','대기 목표','대기오염물질 배출 목표 수립','AIR')],
        )
        self.assertEqual(result['state'],'NO_COMMON_TOPIC_BRIDGE')
        self.assertEqual(result['action_evidence_ids'],[])

    def test_air_action_does_not_bridge_water_topic(self):
        result=evaluate_semantic_bridge(
            {'domain':'WATER'},
            [ev('O1','TN_TOTAL','DIRECTIONAL_DOWN','WATER'),ev('O2','TOC_TOTAL','LEVEL_SHIFT','WATER')],
            [ev('A1','요소수 제조공정 방지시설','암모니아 및 먼지 저감을 위한 흡수시설 설치','WATER')],
            [ev('I1','K-BREF','폐수처리시설 및 수질 모니터링','WATER')],
            [ev('F1','수질 계획','폐수 관리 개선 계획','WATER')],
        )
        self.assertEqual(result['state'],'NO_COMMON_TOPIC_BRIDGE')

    def test_aggregate_chemical_total_requires_driver(self):
        result=evaluate_semantic_bridge(
            {'domain':'CHEMICALS'},
            [ev('O1','Repeated chemical evidence','CHEMICAL_RELEASE_TOTAL:LEVEL_SHIFT_CANDIDATE','CHEMICALS')],
            [ev('A1','유해화학물질 하역장 트렌치','누유출 예방','CHEMICALS')],
            [ev('I1','K-BREF','암모니아 보관 및 취급','CHEMICALS')],
            [ev('F1','화학물질 관리','유해화학물질 관리 강화','CHEMICALS')],
        )
        self.assertEqual(result['state'],'CHEMICAL_AGGREGATE_DRIVER_REQUIRED')
        self.assertEqual(result['anchors'],[])


if __name__=='__main__': unittest.main()
