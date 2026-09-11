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

quality_guard = r'''

# Flattened-text fallbacks are intentionally weaker than structured cards/tables.  A
# nearby sentence fragment can happen to end in an operational suffix (for example a
# prose phrase such as "...한 공장"), so suffix matching alone is not enough to promote
# it as a facility name.  These guards are lexical/grammatical and company-agnostic.
GENERIC_BARE_SITE_LABELS = {
    "공장", "사업장", "센터", "영업소", "사무소", "캠퍼스",
    "주요공장", "주요사업장", "국내공장", "국내사업장",
}
DESCRIPTIVE_SITE_PREFIX_RE = re.compile(
    r"(?:^|\s)[가-힣]+(?:하는|한|있는|없는|되는|된|중인|하던|했던)\s*$"
)
ACCOUNTING_SITE_CONTEXT_RE = re.compile(
    r"(?:단위|금액|매출|매출액|자산|백만원|천만원|억원|만원|천원|원)\)?\s*$",
    re.I,
)


def _prose_like_site_name(value: str, company: str) -> bool:
    """Reject sentence/table fragments that only *look* like facility labels.

    This is deliberately not a company allow-list.  It only rejects shapes that cannot
    safely be treated as a proper facility label in a flattened-text fallback.  A label
    equal to the company name plus a separated suffix remains valid even when the legal
    name itself happens to end with an adnominal-looking Korean syllable.
    """
    name = re.sub(r"\s+", " ", str(value or "")).strip(" -:：|")
    compact = re.sub(r"\s+", "", name)
    if compact in GENERIC_BARE_SITE_LABELS:
        return True

    # A proper label may contain balanced corporate parentheses such as ``(주)`` but a
    # dangling closing bracket is a strong sign that the token leaked from a table unit
    # or preceding prose, e.g. ``백만원) 사업장``.
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        if name.count(closing) > name.count(opening):
            return True

    suffix = next((s for s in OPERATIONAL_SUFFIXES if name.endswith(s)), "")
    if not suffix:
        return False
    prefix = name[:-len(suffix)].strip()
    if not prefix:
        return compact in GENERIC_BARE_SITE_LABELS

    company_compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", str(company or "")).casefold()
    prefix_compact = re.sub(r"[^0-9A-Za-z가-힣]+", "", prefix).casefold()
    if company_compact and prefix_compact == company_compact:
        return False

    if ACCOUNTING_SITE_CONTEXT_RE.search(prefix):
        return True

    # When the suffix is written as a separate word, an immediately preceding Korean
    # adnominal form is prose ("보유한 공장", "운영하는 사업장"), not a site label.
    if re.search(r"\s" + re.escape(suffix) + r"$", name) and DESCRIPTIVE_SITE_PREFIX_RE.search(prefix):
        return True
    return False
'''

insert_anchor = '\n\ndef _operational_name(value: str, company: str) -> str:\n'
if '_prose_like_site_name(' not in catalog:
    if insert_anchor not in catalog:
        raise RuntimeError('patch anchor missing: site quality helper insertion')
    catalog = catalog.replace(insert_anchor, quality_guard + insert_anchor, 1)

catalog = replace_once(
    catalog,
    '    if _non_site_ui_name(name):\n        return ""\n    return name\n',
    '    if _non_site_ui_name(name) or _prose_like_site_name(name, company):\n        return ""\n    return name\n',
    'operational name quality guard',
)

CATALOG.write_text(catalog, encoding='utf-8')


tests = TESTS.read_text(encoding='utf-8')
new_tests = r'''

    def test_flattened_fallback_rejects_prose_and_table_fragments_before_real_catalog(self):
        noisy = Page(
            "https://official.example/esg/overview",
            (
                "국내사업장 당사는 여러 지역에 보유한 공장 서울특별시 서초구 산업로 10 "
                "단위: 백만원) 사업장 전북 익산시 산업로 20 "
                "백만원) 사업장 충청남도 서산시 대산읍 산업2로 30"
            ),
            "",
            200,
        )
        real = Page(
            "https://official.example/company/global-network",
            (
                "글로벌네트워크 생산공장 "
                "서울 본사 서울특별시 서초구 산업로 10 "
                "익산공장 전북 익산시 산업로 20 "
                "대산 제2공장 충청남도 서산시 대산읍 산업2로 30"
            ),
            "",
            200,
        )
        result = catalog.discover("예시소재", [noisy, real])
        self.assertIsNotNone(result)
        sites, scope, unresolved = result
        self.assertEqual(
            {site["site_name_raw"] for site in sites},
            {"서울 본사", "익산공장", "제2공장"},
        )
        self.assertTrue(all(site["source_locator"] == real.url for site in sites))
        self.assertTrue(all(
            site["discovery_evidence"]["extraction_contract"] == "FLATTENED_TEXT_FALLBACK"
            for site in sites
        ))
        self.assertEqual(scope["mode"], "SITE_SET")
        self.assertEqual(unresolved, [])

    def test_site_name_quality_guard_is_company_agnostic_and_preserves_real_labels(self):
        self.assertEqual(catalog._operational_name("보유한 공장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("운영하는 사업장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("백만원) 사업장", "예시회사"), "")
        self.assertEqual(catalog._operational_name("대구 공장", "예시회사"), "대구 공장")
        self.assertEqual(catalog._operational_name("대전 사업장", "예시회사"), "대전 사업장")
        self.assertEqual(catalog._operational_name("판교 R&D 캠퍼스", "예시회사"), "판교 R&D 캠퍼스")
        self.assertEqual(catalog._operational_name("대한 공장", "대한"), "대한 공장")
'''

main_anchor = '\n\nif __name__ == "__main__":\n'
if 'test_flattened_fallback_rejects_prose_and_table_fragments_before_real_catalog' not in tests:
    if main_anchor not in tests:
        raise RuntimeError('patch anchor missing: tests insertion')
    tests = tests.replace(main_anchor, new_tests + main_anchor, 1)

TESTS.write_text(tests, encoding='utf-8')
print('Applied generic flattened-site name quality guard and regressions.')
