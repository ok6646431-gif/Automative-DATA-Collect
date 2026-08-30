import json
from pathlib import Path

PATH = Path('requests/document_evidence.json')
POLICY_PAGE_GLOBAL = 'https://www.samsung.com/global/sustainability/digital-library/policy-document/'
POLICY_PAGE_KR = 'https://www.samsung.com/sec/sustainability/digital-library/policy-document/'

FALLBACKS = {
    'SAMSUNG_SEC_PRODUCT_ENV_RULE_CURRENT': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AYVhebWqCXoAIx95/Standards_for_Control_of_Substances_Used_in_Products_EN.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library current Rev.29 English mirror; same current revision as Korean primary.'
        }
    ],
    'SAMSUNG_REGULATED_SUBSTANCES_CURRENT': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AYVhU6GKB_YAIx95/List%20of%20Regulated%20Substances.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library official current regulated-substances document.'
        }
    ],
    'SAMSUNG_EHS_POLICY_CURRENT': [
        {
            'source_url': 'https://download.semiconductor.samsung.com/resources/others/Environmental_Health_and_Safety_Management_Policy_KR.pdf',
            'source_locator': 'https://semiconductor.samsung.com/kr/sustainability/highlights/downloads/environmental-rules-and-guidelines/',
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung Semiconductor official Korean distribution of the current 2026-02-13 EHS policy.'
        },
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AYVheji6CZcAIx95/Environmental_Health_and_Safety_Management_Policy_EN.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library current English EHS policy.'
        }
    ],
    'SAMSUNG_GREEN_PROCUREMENT_POLICY': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AYTGcZ56AS8AIyDc/Green_Procurement_Policy_new.pdf',
            'source_locator': POLICY_PAGE_KR,
            'expected_extension': 'pdf',
            'verification_status': 'SOURCE_VERIFIED',
            'notes': 'Same Samsung policy-file ID as Korean source; global route returns the verified 5-page Korean Green Procurement PDF when sec route is blocked to GitHub Actions.'
        },
        {
            'source_url': 'https://images.samsung.com/kdp/aboutsamsung/overview/Green_Procurement_Policy_new.pdf',
            'source_locator': POLICY_PAGE_KR,
            'expected_extension': 'pdf',
            'verification_status': 'SOURCE_VERIFIED',
            'notes': 'Samsung official images CDN mirror; verified PDF payload is the Green Procurement Policy.'
        }
    ],
    'SAMSUNG_BIODIVERSITY_POLICY': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AZk839F6KTAALYM-/Samsung_Electronics_Approach_to_Biodiversity.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library official biodiversity policy.'
        }
    ],
    'SAMSUNG_ENV_STRATEGY_CURRENT': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/planet/environmental-strategy/',
            'source_locator': 'https://www.samsung.com/global/sustainability/planet/environmental-strategy/',
            'expected_extension': 'html',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global official current Environmental Strategy page equivalent to blocked Korean route.'
        }
    ],
    'SAMSUNG_SUSTAINABILITY_DATA_CURRENT': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/digital-library/facts-figures/',
            'source_locator': 'https://www.samsung.com/global/sustainability/digital-library/facts-figures/',
            'expected_extension': 'html',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global official current Facts & Figures page including environmental and DS performance data.'
        }
    ],
    'SAMSUNG_AWS_COMMITMENT': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AZAqc8uqGOMALYNu/AWS_Commitment_EN.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library official AWS Commitment document.'
        }
    ],
    'SAMSUNG_AWS_OUTCOMES': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AZsmf03KT5EALYMV/AWS_Outcomes_Announcement_EN.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library official AWS Outcomes & Announcement document.'
        }
    ],
    'SAMSUNG_ZERO_WASTE_TO_LANDFILL': [
        {
            'source_url': 'https://www.samsung.com/global/sustainability/policy-file/AYVhTqy6B3wAIx95/Zero_Waste_to_Landifll_Platinum_Operation.pdf',
            'source_locator': POLICY_PAGE_GLOBAL,
            'expected_extension': 'pdf',
            'verification_status': 'VERIFIED',
            'notes': 'Samsung global Digital Library official UL Zero Waste to Landfill verification document.'
        }
    ],
}


def main():
    evidence = json.loads(PATH.read_text(encoding='utf-8'))
    docs = evidence.get('documents') or []
    by_id = {d.get('document_id'): d for d in docs}
    missing = sorted(set(FALLBACKS) - set(by_id))
    if missing:
        raise SystemExit(f'missing document ids: {missing}')

    # Use the current Korean Green Procurement filename as the primary declaration.
    green = by_id['SAMSUNG_GREEN_PROCUREMENT_POLICY']
    green['source_url'] = 'https://www.samsung.com/sec/sustainability/policy-file/AYTGcZ56AS8AIyDc/Green_Procurement_Policy_new.pdf'

    for document_id, fallbacks in FALLBACKS.items():
        doc = by_id[document_id]
        doc['fallback_sources'] = fallbacks

    for document_id in FALLBACKS:
        doc = by_id[document_id]
        urls = [str(doc.get('source_url') or '')] + [str(x.get('source_url') or '') for x in doc.get('fallback_sources') or []]
        if len(urls) != len(set(urls)):
            raise SystemExit(f'duplicate source URL for {document_id}')
        if any(not u.startswith('https://') for u in urls):
            raise SystemExit(f'non-https source URL for {document_id}')

    evidence.setdefault('discovery_scope', {})['fallback_policy'] = (
        'When a VERIFIED Samsung Korean route is blocked to GitHub Actions, use only independently verified '
        'Samsung-owned global, semiconductor, or images CDN equivalents. Fallback success does not change document identity.'
    )
    PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'patched_documents': sorted(FALLBACKS), 'count': len(FALLBACKS)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
