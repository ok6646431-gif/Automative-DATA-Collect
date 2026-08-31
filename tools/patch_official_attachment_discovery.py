from pathlib import Path
import json

collector = Path('collectors/corporate_docs_collect.py')
text = collector.read_text(encoding='utf-8')
text = text.replace(
    'from urllib.parse import unquote, urlparse\n',
    'from urllib.parse import unquote, urlparse, urljoin\nfrom html.parser import HTMLParser\n',
)

anchor = '''def is_http_url(value):
    try:
        return urlparse(str(value or "")).scheme in {"http", "https"}
    except Exception:
        return False


'''
replacement = '''def is_http_url(value):
    try:
        return urlparse(str(value or "")).scheme in {"http", "https"}
    except Exception:
        return False


class _AttachmentLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self._href=None; self._parts=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href"); self._parts=[]
    def handle_data(self, data):
        if self._href is not None:
            self._parts.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._parts).strip()))
            self._href=None; self._parts=[]


def _norm_match_text(value):
    return re.sub(r"\\s+", "", str(value or "")).lower()


def discover_attachment_candidates(session, doc):
    """Discover one unambiguous official attachment from a verified landing page.

    The feature is opt-in. By default the resolved attachment must remain on the
    same host, match the declared extension, and uniquely win configured match
    terms. Ambiguity fails closed instead of guessing which attachment to use.
    """
    cfg = doc.get("attachment_discovery")
    if not cfg:
        return []
    if cfg is True:
        cfg = {}
    page_url = str(cfg.get("page_url") or doc.get("source_locator") or doc.get("source_url") or "")
    if not is_http_url(page_url):
        return []
    expected = str(doc.get("expected_extension") or "").lower().lstrip(".")
    match_terms = [_norm_match_text(x) for x in (cfg.get("match_terms") or []) if str(x or "").strip()]
    same_host_only = bool(cfg.get("same_host_only", True))
    try:
        with session.get(page_url, timeout=PREFLIGHT_TIMEOUT, allow_redirects=True) as r:
            r.raise_for_status()
            body = getattr(r, "text", None)
            if body is None:
                raw = getattr(r, "body", b"")
                body = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
            resolved_page = str(getattr(r, "url", None) or page_url)
            PREFLIGHT_CACHE[page_url] = {"Referer": resolved_page}
    except Exception:
        return []
    parser = _AttachmentLinkParser()
    try:
        parser.feed(body)
    except Exception:
        return []
    page_host = urlparse(resolved_page).netloc.lower()
    candidates=[]; seen=set()
    for href, label in parser.links:
        url = urljoin(resolved_page, str(href or "").strip())
        if not is_http_url(url) or url in seen:
            continue
        seen.add(url)
        if same_host_only and urlparse(url).netloc.lower() != page_host:
            continue
        combined = _norm_match_text(f"{label} {url}")
        label_ext = Path(str(label or "").strip()).suffix.lower().lstrip(".")
        url_ext = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")
        if expected and expected not in {label_ext, url_ext} and f".{expected}" not in combined:
            continue
        score = sum(1 for term in match_terms if term and term in combined)
        if match_terms and score == 0:
            continue
        candidate = dict(doc)
        candidate.update({
            "source_url": url,
            "source_locator": resolved_page,
            "verification_status": str(doc.get("verification_status") or "UNVERIFIED"),
            "_source_role": "DISCOVERED_ATTACHMENT",
            "_source_order": -1,
            "_source_note": f"official_landing_page_attachment; label={label}",
        })
        candidates.append((score, combined, candidate))
    if not candidates:
        return []
    candidates.sort(key=lambda x: (-x[0], x[1]))
    top_score = candidates[0][0]
    winners = [x[2] for x in candidates if x[0] == top_score]
    return winners if len(winners) == 1 else []


'''
if anchor not in text:
    raise SystemExit('is_http_url anchor not found')
text = text.replace(anchor, replacement, 1)

loop_anchor = '        for candidate in source_candidates(doc):\n'
loop_replacement = '''        candidates = source_candidates(doc)
        discovered = discover_attachment_candidates(session, doc)
        if discovered:
            candidates = discovered + [
                c for c in candidates
                if str(c.get("_source_role") or "").startswith("FALLBACK_")
            ]

        for candidate in candidates:
'''
if loop_anchor not in text:
    raise SystemExit('candidate loop anchor not found')
text = text.replace(loop_anchor, loop_replacement, 1)
text = text.replace(
    'downloaded += 1; fallback_downloaded += int(role != "PRIMARY"); success = True; break',
    'downloaded += 1; fallback_downloaded += int(role.startswith("FALLBACK_")); success = True; break',
)
collector.write_text(text, encoding='utf-8')

# Regression: landing-page link text identifies a PDF even when the download URL has no extension.
test = Path('tests/test_corporate_docs_collect.py')
t = test.read_text(encoding='utf-8')
test_anchor = '    def test_executable_extension_is_never_collected(self):\n'
new_test = """    def test_verified_landing_page_discovers_unique_same_host_pdf_attachment(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); evidence=root/\"docs.json\"; profile=root/\"profile.json\"; out=root/\"out\"
            profile.write_text(json.dumps({\"request_id\":\"REQ-A\",\"company_id\":\"COMP1\"}),encoding=\"utf-8\")
            doc={
                \"document_id\":\"BAT1\",\"document_type\":\"BAT_REFERENCE\",\"title\":\"반도체 최적가용기법 기준서\",
                \"source_url\":\"https://official.example/board/664\",\"source_locator\":\"https://official.example/board/664\",
                \"expected_extension\":\"pdf\",\"verification_status\":\"VERIFIED\",
                \"attachment_discovery\":{\"match_terms\":[\"반도체\",\"최적가용기법\",\"기준서\"],\"same_host_only\":True}
            }
            evidence.write_text(json.dumps({\"schema_version\":\"1.0\",\"request_id\":\"REQ-A\",\"discovery_status\":\"COMPLETE\",\"documents\":[doc]}),encoding=\"utf-8\")
            html='<html><a href=\"/jfile/readDownloadFile.do?fileId=16&fileSeq=2\">반도체 제조업의 환경오염방지 및 통합관리를 위한 최적가용기법 기준서.pdf</a></html>'
            page=FakeResponse(body=html.encode(\"utf-8\"),content_type=\"text/html\",disposition=\"\",url=\"https://official.example/board/664\")
            pdf=FakeResponse(body=b\"%PDF-kbref\",content_type=\"application/pdf\",disposition='attachment; filename=\"kbref.pdf\"',url=\"https://official.example/jfile/readDownloadFile.do?fileId=16&fileSeq=2\")
            session=unittest.mock.MagicMock(); session.get.side_effect=[page,pdf]
            with patch(\"corporate_docs_collect.requests.Session\",return_value=session):
                status=collect(evidence,profile,out)
            self.assertEqual(status[\"downloaded\"],1)
            self.assertEqual(status[\"failed\"],0)
            rows=list(csv.DictReader((out/\"document_index.csv\").open(encoding=\"utf-8-sig\")))
            self.assertEqual(rows[0][\"collection_status\"],\"DOWNLOADED\")
            self.assertIn(\"readDownloadFile.do\",rows[0][\"source_url\"])
            self.assertIn(\"source_selection=DISCOVERED_ATTACHMENT\",rows[0][\"notes\"])
            attempts=list(csv.DictReader((out/\"download_attempts.csv\").open(encoding=\"utf-8-sig\")))
            self.assertEqual(attempts[0][\"source_role\"],\"DISCOVERED_ATTACHMENT\")

"""
if test_anchor not in t:
    raise SystemExit('test anchor not found')
t = t.replace(test_anchor, new_test + test_anchor, 1)
test.write_text(t, encoding='utf-8')

p = Path('requests/document_evidence.json')
data = json.loads(p.read_text(encoding='utf-8'))
data['discovery_scope']['scope_note'] = (
    '삼성전자 Digital Library Planet 환경 정책·문서와 삼성반도체 DS 공식 환경/SHE 페이지 및 '
    '국내 핵심 생산사업장 5개(기흥·화성·평택·천안·온양)를 중심으로 한다. 수원 SAIT는 정책·연구거점 '
    '보조근거로만 보존한다. 제품별 LCA, 개별 국가 제품 규제 선언서, 비환경 People/Principle 문서는 '
    '본 환경관리 학습 수집 범위에서 제외한다.'
)
for d in data.get('documents', []):
    if d.get('document_id') == 'NIER_SEMICONDUCTOR_KBREF_2019':
        d['expected_extension'] = 'pdf'
        d['attachment_discovery'] = {
            'match_terms': ['반도체', '최적가용기법', '기준서'],
            'same_host_only': True,
        }
        d['notes'] = (
            'Official NIER/IEPS K-BREF landing page. Collector must resolve and validate the same-host '
            'PDF attachment; landing-page HTML alone is not accepted as the technical full text.'
        )
for g in data.get('gaps', []):
    if g.get('gap_id') == 'SOURCE_NATIVE_SITE_VARIANTS_REQUIRE_POST_COLLECTION_MATCHING':
        g['reason'] = (
            '사업장명 표기가 소스별로 달라 핵심 생산사업장 5개 Identity 기준으로 결과를 재필터링한다. '
            '수원 SAIT는 보조 후보로만 보존한다.'
        )
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('patched generic official attachment discovery and Samsung K-BREF evidence')
