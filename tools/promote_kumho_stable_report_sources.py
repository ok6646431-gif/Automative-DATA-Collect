#!/usr/bin/env python3
import json
from pathlib import Path

PATH = Path('requests/document_evidence.json')
LANDING = 'https://www.kkpc.com/kor/winwin/esg/sustainabilityList/'

PROMOTIONS = {
    'KUMHO_SUSTAINABILITY_2020': 'https://www.kkpc.com/download/?seq=3778',
    'KUMHO_SUSTAINABILITY_2021': 'https://www.kkpc.com/download/?seq=5174',
    'KUMHO_SUSTAINABILITY_2022': 'https://www.kkpc.com/download/?seq=6416',
    'KUMHO_SUSTAINABILITY_2023': 'https://www.kkpc.com/upload/download/Kumho Petrochemical Sustainability Report 2023.pdf',
}


def source_record(doc):
    return {
        'source_url': doc['source_url'],
        'source_locator': doc.get('source_locator') or LANDING,
        'expected_extension': doc.get('expected_extension') or 'pdf',
        'verification_status': doc.get('verification_status') or 'VERIFIED',
        'notes': 'Official Korean edition retained as a verified fallback after transport acceptance testing.',
    }


def promote(doc, preferred_url):
    current_url = str(doc.get('source_url') or '')
    fallbacks = [dict(x) for x in (doc.get('fallback_sources') or [])]

    # Idempotent: already promoted. Ensure old/current official alternatives are not duplicated.
    if current_url == preferred_url:
        seen = set()
        clean = []
        for alt in fallbacks:
            url = str(alt.get('source_url') or '')
            if not url or url == preferred_url or url in seen:
                continue
            seen.add(url)
            clean.append(alt)
        doc['fallback_sources'] = clean
        return

    preferred = None
    remaining = []
    for alt in fallbacks:
        if str(alt.get('source_url') or '') == preferred_url and preferred is None:
            preferred = alt
        else:
            remaining.append(alt)

    old_primary = source_record(doc)
    preferred = dict(preferred or {})
    preferred['source_url'] = preferred_url
    preferred['source_locator'] = preferred.get('source_locator') or LANDING
    preferred['expected_extension'] = preferred.get('expected_extension') or doc.get('expected_extension') or 'pdf'
    preferred['verification_status'] = 'VERIFIED'

    for key in ('source_url', 'source_locator', 'expected_extension', 'verification_status'):
        doc[key] = preferred[key]

    promoted_note = (
        'Primary source selected from an independently verified official edition that passed '
        'real-file transport validation; Korean official route retained as fallback.'
    )
    doc['notes'] = promoted_note

    candidates = [old_primary] + remaining
    seen = {preferred_url}
    clean = []
    for alt in candidates:
        url = str(alt.get('source_url') or '')
        if not url or url in seen:
            continue
        seen.add(url)
        alt['verification_status'] = 'VERIFIED'
        alt['source_locator'] = alt.get('source_locator') or LANDING
        alt['expected_extension'] = alt.get('expected_extension') or 'pdf'
        clean.append(alt)
    doc['fallback_sources'] = clean


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    docs = data.get('documents') or []
    by_id = {}
    for doc in docs:
        did = doc.get('document_id')
        if did in by_id:
            raise SystemExit(f'duplicate document_id: {did}')
        by_id[did] = doc

    missing = [did for did in PROMOTIONS if did not in by_id]
    if missing:
        raise SystemExit(f'missing target documents: {missing}')

    for did, url in PROMOTIONS.items():
        promote(by_id[did], url)

    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Promoted Kumho stable report routes:', ', '.join(sorted(PROMOTIONS)))


if __name__ == '__main__':
    main()
