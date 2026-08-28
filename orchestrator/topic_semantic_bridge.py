"""Require topic-level semantic coherence before declaring four-layer readiness.

Cross-layer evidence is first grouped by broad environmental domain.  That is useful
for discovery but too permissive for a final READY state: an AIR action about dust
must not satisfy a NOx/SOx topic merely because both are AIR.  This module derives
observed subtopic anchors and checks whether at least one anchor is supported by a
same-site company action plus industry and future-direction context.

The gate is deliberately fail-closed.  Aggregate chemical-release totals require a
substance-level driver before they can become FOUR_LAYER_READY.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Set


ANCHORS = {
    'AIR': {
        'NOX': ['nox', '질소산화물', '질소 산화물', '탈질', 'scr', 'sncr'],
        'SOX': ['sox', '황산화물', '황 산화물', '탈황', 'fgd'],
        'DUST': ['먼지', '분진', '미세먼지', 'dust', '집진'],
        'VOC': ['voc', '휘발성유기', '휘발성 유기', 'rto'],
        'HCL': ['hcl', '염화수소'],
        'HF': ['hf', '불화수소', '불산'],
        'CO': ['일산화탄소', 'carbon monoxide'],
    },
    'WATER': {
        'SS': ['ss_total', '부유물질', '부유 고형물', 'suspended solids'],
        'TN': ['tn_total', 't-n', '총질소', 'total nitrogen'],
        'TP': ['tp_total', 't-p', '총인', 'total phosphorus'],
        'TOC': ['toc_total', '총유기탄소', 'total organic carbon'],
        'COD': ['cod', '화학적산소요구량', 'chemical oxygen demand'],
        'BOD': ['bod', '생물화학적산소요구량', 'biochemical oxygen demand'],
    },
    'GHG_ENERGY': {
        'GHG': ['온실가스', 'greenhouse gas', 'scope 1', 'scope1', 'scope 2', 'scope2'],
        'ENERGY': ['에너지', '전력', 'energy', 'electricity'],
    },
    'WASTE': {
        'WASTE': ['폐기물', 'waste'],
        'RECYCLING': ['재활용', '자원순환', 'recycle', 'recycling'],
    },
    'WATER_RESOURCES': {
        'WATER_USE': ['용수', '취수', 'water use', 'water withdrawal'],
        'WATER_REUSE': ['재이용', '재사용', 'water reuse', 'reclaimed water'],
    },
    'CHEMICALS': {
        'AMMONIA': ['암모니아', 'nh3'],
        'BENZENE': ['벤젠', 'benzene'],
        'TOLUENE': ['톨루엔', 'toluene'],
        'XYLENE': ['자일렌', 'xylene'],
        'HCL': ['염화수소', 'hcl'],
        'HF': ['불화수소', '불산', 'hf'],
        'SULFURIC_ACID': ['황산', 'sulfuric acid'],
    },
}

DOMAIN_GENERIC = {
    'AIR': ['대기오염', '대기 배출', '대기배출', '배출가스', 'air emission', 'air pollut'],
    'WATER': ['폐수', '수질', '방류수', 'wastewater', 'water quality', '수처리'],
    'WATER_RESOURCES': ['용수', '수자원', 'water stewardship', 'water use', '취수'],
    'WASTE': ['폐기물', '자원순환', 'waste management'],
    'GHG_ENERGY': ['온실가스', '탄소중립', '에너지', '전력', 'greenhouse gas', 'net zero'],
    'CHEMICALS': ['화학물질', '유해화학물질', 'chemical management', 'chemical substance'],
}

CHEMICAL_AGGREGATE_MARKERS = [
    'chemical_release_total', 'chemical transfer total', 'chemical_transfer_total',
    'repeated chemical evidence', 'prtr total', '배출이동량 총', '화학물질 총량',
]


def _text(evidence: Dict) -> str:
    return (' '.join([
        str(evidence.get('title') or ''),
        str(evidence.get('statement') or ''),
    ])).lower()


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(str(term).lower() in text for term in terms)


def observed_anchors(domain: str, observed: List[Dict]) -> Dict:
    domain = str(domain or '').upper()
    text = ' '.join(_text(e) for e in observed)
    found: Set[str] = set()
    for anchor, terms in (ANCHORS.get(domain) or {}).items():
        if _has_any(text, terms):
            found.add(anchor)

    if domain == 'CHEMICALS':
        aggregate = _has_any(text, CHEMICAL_AGGREGATE_MARKERS)
        # Generic PRTR/chemical totals are intentionally non-bridgeable until a
        # substance-level driver has been identified in the observed evidence.
        if aggregate and not found:
            return {
                'anchors': [],
                'state': 'CHEMICAL_AGGREGATE_DRIVER_REQUIRED',
                'note': 'Aggregate chemical-release/transfer signal lacks a substance-level observed driver.',
            }
        if not found:
            return {
                'anchors': [],
                'state': 'CHEMICAL_DRIVER_REQUIRED',
                'note': 'Chemical topic lacks a recognized substance-level observed anchor.',
            }

    if found:
        return {'anchors': sorted(found), 'state': 'ANCHORS_FOUND', 'note': ''}
    return {
        'anchors': [domain + '_GENERIC'],
        'state': 'DOMAIN_GENERIC',
        'note': 'No specific observed subtopic anchor was recognized; strong domain-generic evidence is required.',
    }


def _supports(domain: str, anchor: str, evidence: Dict, allow_domain_generic: bool = True) -> bool:
    text = _text(evidence)
    if anchor.endswith('_GENERIC'):
        return _has_any(text, DOMAIN_GENERIC.get(domain, []))
    if _has_any(text, (ANCHORS.get(domain) or {}).get(anchor, [])):
        return True
    return bool(allow_domain_generic and _has_any(text, DOMAIN_GENERIC.get(domain, [])))


def evaluate_semantic_bridge(
    topic: Dict,
    observed: List[Dict],
    actions: List[Dict],
    semantic_industry: List[Dict],
    future: List[Dict],
) -> Dict:
    """Return a fail-closed semantic bridge decision for one cross-layer topic."""
    domain = str(topic.get('domain') or '').upper()
    obs = observed_anchors(domain, observed)
    anchors = obs['anchors']
    if not anchors:
        return {
            'state': obs['state'], 'anchors': [],
            'action_evidence_ids': [], 'industry_evidence_ids': [], 'future_evidence_ids': [],
            'note': obs['note'],
        }

    matched_anchors = []
    action_ids: Set[str] = set()
    industry_ids: Set[str] = set()
    future_ids: Set[str] = set()
    layer_failures = []

    for anchor in anchors:
        a = [e for e in actions if _supports(domain, anchor, e, allow_domain_generic=True)]
        # Industry/future context may be broader than the observed metric, but it
        # must still explicitly discuss the same environmental domain.
        i = [e for e in semantic_industry if _supports(domain, anchor, e, allow_domain_generic=True)]
        f = [e for e in future if _supports(domain, anchor, e, allow_domain_generic=True)]
        if a and i and f:
            matched_anchors.append(anchor)
            action_ids.update(e.get('evidence_id','') for e in a if e.get('evidence_id'))
            industry_ids.update(e.get('evidence_id','') for e in i if e.get('evidence_id'))
            future_ids.update(e.get('evidence_id','') for e in f if e.get('evidence_id'))
        else:
            missing=[]
            if not a: missing.append('company_action')
            if not i: missing.append('industry')
            if not f: missing.append('future')
            layer_failures.append(anchor+':'+'/'.join(missing))

    if matched_anchors:
        return {
            'state': 'READY',
            'anchors': sorted(matched_anchors),
            'action_evidence_ids': sorted(action_ids),
            'industry_evidence_ids': sorted(industry_ids),
            'future_evidence_ids': sorted(future_ids),
            'note': 'At least one observed subtopic has a same-topic company action plus industry and future-direction context.',
        }

    return {
        'state': 'NO_COMMON_TOPIC_BRIDGE',
        'anchors': anchors,
        'action_evidence_ids': [], 'industry_evidence_ids': [], 'future_evidence_ids': [],
        'note': 'Broad-domain layers exist but no observed subtopic is supported across all required layers. ' + '; '.join(layer_failures),
    }
