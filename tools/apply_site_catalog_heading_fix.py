from pathlib import Path

CATALOG = Path('orchestrator/g0_domestic_site_catalog.py')
TESTS = Path('tests/test_g0_domestic_site_catalog.py')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f'patch anchor missing: {label}')
    return text.replace(old, new, 1)


catalog = CATALOG.read_text(encoding='utf-8')

catalog = replace_once(
    catalog,
    '    "제철소", "공장", "연구소", "기술원", "사업장", "센터", "영업소", "사무소", "본사",\n',
    '    "제철소", "공장", "연구소", "기술원", "사업장", "센터", "영업소", "사무소", "본사", "캠퍼스",\n',
    'operational campus suffix',
)

catalog = replace_once(
    catalog,
    '    r"[가-힣0-9·.\\-]{1,36}(?:대로|로|길)\\s*\\d+(?:[-~]\\d+)?)"\n',
    '    r"[가-힣0-9·.\\-]{1,36}(?:대로|로|길)\\s*\\d+(?:[-~]\\d+)?(?:번길\\s*\\d+(?:[-~]\\d+)?)?)"\n',
    'nested beon-gil road address',
)

semantic_function = r'''

def _semantic_heading_sites(company: str, page: base.Page) -> Dict[str, Dict[str, Any]]:
    """Pair semantic facility headings with the next bounded Korean road address.

    Some official location pages use clean HTML headings (for example a headquarters,
    R&D campus, or service center) but do not expose ``name``/``address`` CSS classes.
    Flattening such a page destroys card boundaries and can reuse the previous facility
    name for the next address.  On an already-confirmed first-party catalog page, a
    semantic heading followed by exactly one road address before the next facility
    heading is a stronger contract than proximity in flattened text.
    """
    html = str(page.html or "")
    if not html.strip():
        return {}
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    heading_names = {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "strong"}

    headings: List[Tuple[Any, str]] = []
    for tag in soup.find_all(True):
        role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
        if getattr(tag, "name", "") not in heading_names and role != "heading" and not _class_matches(tag, NAME_CLASS_HINTS):
            continue
        raw = _clean_cell(" ".join(tag.stripped_strings))
        name = _operational_name(raw, company)
        if name:
            headings.append((tag, name))

    for heading, name in headings:
        address = ""
        scanned = 0
        for tag in heading.find_all_next(True):
            scanned += 1
            if scanned > 40:
                break
            if tag is not heading:
                role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
                if getattr(tag, "name", "") in heading_names or role == "heading" or _class_matches(tag, NAME_CLASS_HINTS):
                    next_name = _operational_name(_clean_cell(" ".join(tag.stripped_strings)), company)
                    if next_name:
                        break
            value = _clean_cell(" ".join(tag.stripped_strings))
            matches = list(CATALOG_ROAD_ADDRESS_RE.finditer(value))
            if len(matches) != 1:
                continue
            candidate = _validated_address(value)
            if candidate:
                address = candidate
                break
        if not address:
            continue
        key = _compact(address)
        if not key:
            continue
        found.setdefault(key, {
            "name": name,
            "address": address,
            "source_locator": page.url,
            "extraction_contract": "SEMANTIC_HEADING_ADDRESS_PAIR",
        })
    return found
'''

anchor = '\n\ndef _bounded_site_name(name: str, company: str) -> str:\n'
if '_semantic_heading_sites(' not in catalog:
    if anchor not in catalog:
        raise RuntimeError('patch anchor missing: semantic heading insertion')
    catalog = catalog.replace(anchor, semantic_function + anchor, 1)

catalog = replace_once(
    catalog,
    '        if len(found) < 2:\n            found = _flattened_text_sites(company, page)\n',
    '        if len(found) < 2:\n            found = _semantic_heading_sites(company, page)\n        if len(found) < 2:\n            found = _flattened_text_sites(company, page)\n',
    'semantic heading discovery order',
)

CATALOG.write_text(catalog, encoding='utf-8')


tests = TESTS.read_text(encoding='utf-8')
new_tests = r'''
    def test_semantic_location_headings_preserve_campus_names_and_full_beongil_addresses(self):
        html = '''<html><body>
          <h2>국내 사업장</h2>
          <section><h3>서울 본사</h3><p>주소 서울특별시 중구 중앙로 86</p></section>
          <section><h3>판교 R&amp;D 캠퍼스</h3><p>주소 경기도 성남시 분당구 혁신로 319번길 6</p></section>
          <section><h3>양주 CS센터</h3><p>주소 경기도 양주시 백석읍 꿈나무로 108</p></section>
          <section><h3>대전 R&amp;D 캠퍼스</h3><p>주소 대전광역시 유성구 연구대로 1366번길 10</p></section>
          <section><h3>대전 사업장</h3><p>주소 대전광역시 유성구 외삼로 8번길 99</p></section>
        </body></html>'''
        text = (
            '국내 사업장 서울 본사 주소 서울특별시 중구 중앙로 86 '
            '판교 R&D 캠퍼스 주소 경기도 성남시 분당구 혁신로 319번길 6 '
            '양주 CS센터 주소 경기도 양주시 백석읍 꿈나무로 108 '
            '대전 R&D 캠퍼스 주소 대전광역시 유성구 연구대로 1366번길 10 '
            '대전 사업장 주소 대전광역시 유성구 외삼로 8번길 99'
        )
        result = catalog.discover(
            '예시항공',
            [Page('https://official.example/company/domestic-sites', text, html, 200)],
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        by_address = {site['address_raw']: site for site in sites}
        self.assertEqual(by_address['경기도 성남시 분당구 혁신로 319번길 6']['site_name_raw'], '판교 R&D 캠퍼스')
        self.assertEqual(by_address['대전광역시 유성구 연구대로 1366번길 10']['site_name_raw'], '대전 R&D 캠퍼스')
        self.assertEqual(by_address['대전광역시 유성구 외삼로 8번길 99']['site_name_raw'], '대전 사업장')
        self.assertEqual(by_address['경기도 양주시 백석읍 꿈나무로 108']['site_name_raw'], '양주 CS센터')
        self.assertTrue(all(site['discovery_evidence']['extraction_contract'] == 'SEMANTIC_HEADING_ADDRESS_PAIR' for site in sites))
        self.assertEqual(scope['mode'], 'SITE_SET')
        self.assertEqual(unresolved, [])

    def test_nested_beongil_address_is_not_truncated(self):
        self.assertEqual(
            catalog._validated_address('주소 경기도 성남시 분당구 혁신로 319번길 6 전화 000'),
            '경기도 성남시 분당구 혁신로 319번길 6',
        )
'''

main_anchor = '\n\nif __name__ == "__main__":\n'
if 'test_semantic_location_headings_preserve_campus_names_and_full_beongil_addresses' not in tests:
    if main_anchor not in tests:
        raise RuntimeError('patch anchor missing: tests insertion')
    tests = tests.replace(main_anchor, '\n' + new_tests + main_anchor, 1)
TESTS.write_text(tests, encoding='utf-8')

print('Applied generic semantic site-heading and nested-beongil fixes.')
