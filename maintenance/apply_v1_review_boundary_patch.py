from pathlib import Path

# --- 1) Domestic-site semantic pairing: support lot-number addresses and stop at structural headings.
path = Path('orchestrator/g0_domestic_site_catalog.py')
text = path.read_text(encoding='utf-8')

anchor = '''CATALOG_ROAD_ADDRESS_RE = re.compile(
    rf"((?:(?:{CATALOG_REGION})\\s+|[가-힣]{{2,24}}(?:특별자치도|특별자치시|광역시|특별시|도)\\s+)"
    r"[가-힣0-9]{1,24}(?:시|군|구)\\s+"
    r"(?:[가-힣0-9]{1,24}(?:읍|면|동|리|구)\\s+)?"
    r"[가-힣0-9·.\\-]{1,36}(?:대로|로|길)\\s*\\d+(?:[-~]\\d+)?(?:번길\\s*\\d+(?:[-~]\\d+)?)?)"
)
'''
if anchor not in text:
    raise SystemExit('road address regex anchor missing')
lot_block = anchor + '''CATALOG_LOT_ADDRESS_RE = re.compile(
    rf"((?:(?:{CATALOG_REGION})\\s+|[가-힣]{{2,24}}(?:특별자치도|특별자치시|광역시|특별시|도)\\s+)"
    r"[가-힣0-9]{1,24}(?:시|군|구)\\s+"
    r"(?:[가-힣0-9]{1,24}(?:읍|면)\\s+)?"
    r"[가-힣0-9·.\\-]{1,36}(?:동|리)\\s+\\d+(?:-\\d+)?)"
)
'''
if 'CATALOG_LOT_ADDRESS_RE' not in text:
    text = text.replace(anchor, lot_block, 1)

old = '''def _validated_address(value: str) -> str:
    text = re.sub(r"\\s+", " ", str(value or "")).strip()
    match = CATALOG_ROAD_ADDRESS_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\\s+", " ", match.group(1)).strip()
'''
new = '''def _address_matches(value: str):
    text = re.sub(r"\\s+", " ", str(value or "")).strip()
    matches = [*CATALOG_ROAD_ADDRESS_RE.finditer(text), *CATALOG_LOT_ADDRESS_RE.finditer(text)]
    return sorted(matches, key=lambda m: (m.start(), -(m.end() - m.start())))


def _validated_address(value: str) -> str:
    matches = _address_matches(value)
    if not matches:
        return ""
    return re.sub(r"\\s+", " ", matches[0].group(1)).strip()
'''
if old not in text:
    raise SystemExit('validated address block missing')
text = text.replace(old, new, 1)

old = '''    address_match = CATALOG_ROAD_ADDRESS_RE.search(address_cell)
    if address_match:
        prefix = _clean_cell(address_cell[:address_match.start()])
'''
new = '''    address_matches = _address_matches(address_cell)
    address_match = address_matches[0] if address_matches else None
    if address_match:
        prefix = _clean_cell(address_cell[:address_match.start()])
'''
if old not in text:
    raise SystemExit('table address match block missing')
text = text.replace(old, new, 1)

old = '''            if CATALOG_ROAD_ADDRESS_RE.search(value):
                continue
'''
new = '''            if _address_matches(value):
                continue
'''
if old not in text:
    raise SystemExit('table candidate address guard missing')
text = text.replace(old, new, 1)

old = '''    heading_names = {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "strong"}
'''
new = '''    heading_names = {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "strong"}
    structural_heading_names = {"h1", "h2", "h3", "h4", "h5", "h6", "dt"}
'''
if old not in text:
    raise SystemExit('heading names block missing')
text = text.replace(old, new, 1)

old = '''            if tag is not heading:
                role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
                if getattr(tag, "name", "") in heading_names or role == "heading" or _class_matches(tag, NAME_CLASS_HINTS):
                    next_name = _operational_name(_clean_cell(" ".join(tag.stripped_strings)), company)
                    if next_name:
                        break
            value = _clean_cell(" ".join(tag.stripped_strings))
            matches = list(CATALOG_ROAD_ADDRESS_RE.finditer(value))
'''
new = '''            if tag is not heading:
                role = str((getattr(tag, "attrs", {}) or {}).get("role") or "").casefold()
                tag_name = getattr(tag, "name", "")
                name_class = _class_matches(tag, NAME_CLASS_HINTS)
                # A real structural heading starts a new catalog record even when the
                # label is a business-unit/legal-entity name rather than ending in
                # "공장" or "사업장". Never borrow an address across that boundary.
                if tag_name in structural_heading_names or role == "heading" or name_class:
                    break
                if tag_name == "strong":
                    next_name = _operational_name(_clean_cell(" ".join(tag.stripped_strings)), company)
                    if next_name:
                        break
            value = _clean_cell(" ".join(tag.stripped_strings))
            matches = _address_matches(value)
'''
if old not in text:
    raise SystemExit('semantic heading scan block missing')
text = text.replace(old, new, 1)

old = '''    for match in CATALOG_ROAD_ADDRESS_RE.finditer(text):
        address = re.sub(r"\\s+", " ", match.group(1)).strip()
'''
new = '''    for match in _address_matches(text):
        address = re.sub(r"\\s+", " ", match.group(1)).strip()
'''
if old not in text:
    raise SystemExit('flattened address iterator missing')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# --- 2) Promotion policy: historical rename ambiguity outside requested window is review-only.
path = Path('orchestrator/g0_promotion_policy.py')
text = path.read_text(encoding='utf-8')
text = text.replace('from typing import Any, Dict, Tuple\n', 'from typing import Any, Dict, Tuple\n\nimport re\n', 1)
anchor = '''NONBLOCKING_PROMOTION_CODES = {
    "CORPORATE_DOCUMENT_COVERAGE_INCOMPLETE",
}
'''
if anchor not in text:
    raise SystemExit('promotion code anchor missing')
helper = anchor + '''

def _requested_start_year(discovery: Dict[str, Any]) -> int | None:
    window = ((discovery.get("collection_policy") or {}).get("requested_history_window") or {})
    try:
        return int(window.get("start_year")) if window.get("start_year") is not None else None
    except (TypeError, ValueError):
        return None


def _historical_name_issue_is_pre_window(
    item: Dict[str, Any], discovery: Dict[str, Any], audit: Dict[str, Any]
) -> bool:
    if str(item.get("code") or "") != "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED":
        return False
    requested_start = _requested_start_year(discovery)
    if requested_start is None:
        return False
    recovery = (((audit.get("stages") or {}).get("official_site") or {}).get("recovery") or {})
    signals = [x for x in recovery.get("rename_signals") or [] if isinstance(x, dict)]
    if not signals:
        return False
    years = []
    for signal in signals:
        value = signal.get("year")
        match = re.search(r"(?:19|20)\\d{2}", str(value or ""))
        if not match:
            return False
        years.append(int(match.group(0)))
    return bool(years) and max(years) < requested_start
'''
if '_historical_name_issue_is_pre_window' not in text:
    text = text.replace(anchor, helper, 1)
old = '''    for item in discovery.get("unresolved_items", []) or []:
        if str(item.get("code") or "") in NONBLOCKING_PROMOTION_CODES:
            deferred.append(item)
        else:
            blocking.append(item)
'''
new = '''    for item in discovery.get("unresolved_items", []) or []:
        code = str(item.get("code") or "")
        if code in NONBLOCKING_PROMOTION_CODES or _historical_name_issue_is_pre_window(item, discovery, audit):
            deferred.append(item)
        else:
            blocking.append(item)
'''
if old not in text:
    raise SystemExit('promotion classification block missing')
text = text.replace(old, new, 1)
old = '''            "Verified identity/site discovery may be promoted with explicit document "
            "coverage gaps; identity/scope/legal ambiguity remains fail-closed."
'''
new = '''            "Verified current-entity discovery may be promoted with explicit document "
            "coverage gaps and historical-name ambiguity proven to predate the requested "
            "history window; current-window identity/scope/legal ambiguity remains fail-closed."
'''
if old not in text:
    raise SystemExit('promotion policy text missing')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# --- Tests.
path = Path('tests/test_g0_domestic_site_catalog.py')
text = path.read_text(encoding='utf-8')
marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
if marker not in text:
    raise SystemExit('domestic site test marker missing')
test = r'''
    def test_semantic_heading_does_not_borrow_address_across_business_heading_and_accepts_lot_address(self):
        html = '''<html><body>
          <h2>국내 사업장</h2>
          <section><h3>첨단소재 여수공장</h3><p>주소 전남 여수시 평여동 62</p></section>
          <section><h3>별도 법인명</h3><p>주소 충남 서산시 대산읍 독곶1로 82</p></section>
          <section><h3>울산공장</h3><p>주소 울산광역시 남구 사평로 119</p></section>
        </body></html>'''
        text = (
            '국내 사업장 첨단소재 여수공장 주소 전남 여수시 평여동 62 '
            '별도 법인명 주소 충남 서산시 대산읍 독곶1로 82 '
            '울산공장 주소 울산광역시 남구 사평로 119'
        )
        result = catalog.discover(
            '예시화학', [Page('https://official.example/company/network', text, html, 200)]
        )
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        by_name = {site['site_name_raw']: site['address_raw'] for site in sites}
        self.assertEqual(by_name['첨단소재 여수공장'], '전남 여수시 평여동 62')
        self.assertEqual(by_name['울산공장'], '울산광역시 남구 사평로 119')
        self.assertNotIn('충남 서산시 대산읍 독곶1로 82', set(by_name.values()))
        self.assertEqual(scope['mode'], 'SITE_SET')
        self.assertEqual(unresolved, [])
'''
if 'test_semantic_heading_does_not_borrow_address_across_business_heading' not in text:
    text = text.replace(marker, '\n' + test + marker, 1)
path.write_text(text, encoding='utf-8')

path = Path('tests/test_g0_promotion_policy.py')
text = path.read_text(encoding='utf-8')
if marker not in text:
    raise SystemExit('promotion test marker missing')
test = r'''
    def test_pre_window_historical_name_ambiguity_is_deferred(self):
        discovery = {
            'collection_policy': {'requested_history_window': {'start_year': 2020, 'end_year': 2026}},
            'unresolved_items': [{'code': 'HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED'}],
        }
        audit = {
            'stages': {'official_site': {'recovery': {'rename_signals': [{'year': 2012}, {'year': 1997}]}}}}
        }
        d, _, a = policy.apply(discovery, {'gaps': []}, audit)
        self.assertEqual(d['unresolved_items'], [])
        self.assertEqual(a['gate_status'], 'PASS')
        self.assertEqual(a['stages']['promotion_policy']['deferred_review_count'], 1)

    def test_current_or_unknown_historical_name_ambiguity_remains_blocking(self):
        for signals in ([{'year': 2021}], [{'year': None}]):
            discovery = {
                'collection_policy': {'requested_history_window': {'start_year': 2020, 'end_year': 2026}},
                'unresolved_items': [{'code': 'HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED'}],
            }
            audit = {'stages': {'official_site': {'recovery': {'rename_signals': signals}}}}
            d, _, a = policy.apply(discovery, {'gaps': []}, audit)
            self.assertEqual(len(d['unresolved_items']), 1)
            self.assertEqual(a['gate_status'], 'REVIEW_REQUIRED')
'''
if 'test_pre_window_historical_name_ambiguity_is_deferred' not in text:
    text = text.replace(marker, '\n' + test + marker, 1)
path.write_text(text, encoding='utf-8')
