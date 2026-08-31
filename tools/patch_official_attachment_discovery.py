from pathlib import Path
import json

collector = Path('collectors/corporate_docs_collect.py')
text = collector.read_text(encoding='utf-8')
text = text.replace('from urllib.parse import unquote, urlparse\n', 'from urllib.parse import unquote, urlparse, urljoin\nfrom html.parser import HTMLParser\n')

needle = '''def is_http_url(value):\n    try:\n        return urlparse(str(value or "")).scheme in {"http", "https"}\n    except Exception:\n        return False\n\n\n'''
insert = '''def is_http_url(value):\n    try:\n        return urlparse(str(value or "")).scheme in {"http", "https"}\n    except Exception:\n        return False\n\n\nclass _AttachmentLinkParser(HTMLParser):\n    def __init__(self):\n        super().__init__(); self.links=[]; self._href=None; self._parts=[]\n    def handle_starttag(self, tag, attrs):\n        if tag.lower() == "a":\n            self._href = dict(attrs).get("href"); self._parts=[]\n    def handle_data(self, data):\n        if self._href is not None:\n            self._parts.append(data)\n    def handle_endtag(self, tag):\n        if tag.lower() == "a" and self._href is not None:\n            self.links.append((self._href, " ".join(self._parts).strip()))\n            self._href=None; self._parts=[]\n\n\ndef _norm_match_text(value):\n    return re.sub(r"\\s+", "", str(value or "")).lower()\n\n\ndef discover_attachment_candidates(session, doc):\n    """Discover one unambiguous official attachment from a verified landing page.\n\n    This is opt-in through attachment_discovery. The landing page remains the\n    provenance locator; a discovered file is accepted only from the same host\n    by default, must match the declared extension, and must uniquely win the\n    configured title/keyword match. Ambiguity fails closed.\n    """\n    cfg = doc.get("attachment_discovery")\n    if not cfg:\n        return []\n    if cfg is True:\n        cfg = {}\n    page_url = str(cfg.get("page_url") or doc.get("source_locator") or doc.get("source_url") or "")\n    if not is_http_url(page_url):\n        return []\n    expected = str(doc.get("expected_extension") or "").lower().lstrip(".")\n    match_terms = [_norm_match_text(x) for x in (cfg.get("match_terms") or []) if str(x or "").strip()]\n    same_host_only = bool(cfg.get("same_host_only", True))\n    try:\n        with session.get(page_url, timeout=PREFLIGHT_TIMEOUT, allow_redirects=True) as r:\n            r.raise_for_status()\n            body = getattr(r, "text", None)\n            if body is None:\n                raw = getattr(r, "body", b"")\n                body = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")\n            resolved_page = str(getattr(r, "url", None) or page_url)\n            PREFLIGHT_CACHE[page_url] = {"Referer": resolved_page}\n    except Exception:\n        return []\n    parser = _AttachmentLinkParser()\n    try:\n        parser.feed(body)\n    except Exception:\n        return []\n    page_host = urlparse(resolved_page).netloc.lower()\n    candidates=[]\n    seen=set()\n    for href, label in parser.links:\n        url = urljoin(resolved_page, str(href or "").strip())\n        if not is_http_url(url) or url in seen:\n            continue\n        seen.add(url)\n        if same_host_only and urlparse(url).netloc.lower() != page_host:\n            continue\n        combined = _norm_match_text(f"{label} {url}")\n        label_ext = Path(str(label or "").strip()).suffix.lower().lstrip(".")\n        url_ext = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")\n        if expected and expected not in {label_ext, url_ext} and f".{expected}" not in combined:\n            continue\n        score = sum(1 for term in match_terms if term and term in combined)\n        if match_terms and score == 0:\n            continue\n        candidate = dict(doc)\n        candidate.update({\n            "source_url": url, "source_locator": resolved_page,\n            "verification_status": str(doc.get("verification_status") or "UNVERIFIED"),\n            "_source_role": "DISCOVERED_ATTACHMENT", "_source_order": -1,\n            "_source_note": f"official_landing_page_attachment; label={label}"\n        })\n        candidates.append((score, combined, candidate))\n    if not candidates:\n        return []\n    candidates.sort(key=lambda x: (-x[0], x[1]))\n    top_score = candidates[0][0]\n    winners = [x[2] for x in candidates if x[0] == top_score]\n    return winners if len(winners) == 1 else []\n\n\n'''
if needle not in text:
    raise SystemExit('is_http_url anchor not found')
text = text.replace(needle, insert, 1)

needle2 = '        for candidate in source_candidates(doc):\n'
replace2 = '''        candidates = source_candidates(doc)\n        discovered = discover_attachment_candidates(session, doc)\n        if discovered:\n            # The declared source_url may itself be only the landing page. Once a\n            # unique verified attachment is resolved, do not download that HTML\n            # page as though it were the document. Keep independently verified\n            # fallback sources after the discovered attachment.\n            candidates = discovered + [c for c in candidates if str(c.get("_source_role") or "").startswith("FALLBACK_")]\n\n        for candidate in candidates:\n'''
if needle2 not in text:
    raise SystemExit('candidate loop anchor not found')
text = text.replace(needle2, replace2, 1)
text = text.replace('downloaded += 1; fallback_downloaded += int(role != "PRIMARY"); success = True; break', 'downloaded += 1; fallback_downloaded += int(role.startswith("FALLBACK_")); success = True; break')
collector.write_text(text, encoding='utf-8')

# Add a regression test for an official landing page whose attachment URL has no file extension.
test = Path('tests/test_corporate_docs_collect.py')
t = test.read_text(encoding='utf-8')
anchor = '    def test_executable_extension_is_never_collected(self):\n'
new_test = '''    def test_verified_landing_page_discovers_unique_same_host_pdf_attachment(self):\n        with tempfile.TemporaryDirectory() as td:\n            root=Path(td); evidence=root/"docs.json"; profile=root/"profile.json"; out=root/"out"\n            profile.write_text(json.dumps({"request_id":"REQ-A","company_id":"COMP1"}),encoding="utf-8")\n            doc={\n                "document_id":"BAT1","document_type":"BAT_REFERENCE","title":"반도체 최적가용기법 기준서",\n                "source_url":"https://official.example/board/664","source_locator":"https://official.example/board/664",\n                "expected_extension":"pdf","verification_status":"VERIFIED",\n                "attachment_discovery":{"match_terms":["반도체","최적가용기법","기준서"],"same_host_only":True}\n            }\n            evidence.write_text(json.dumps({"schema_version":"1.0","request_id":"REQ-A","discovery_status":"COMPLETE","documents":[doc]}),encoding="utf-8")\n            page=FakeResponse(body='''<html><a href="/jfile/readDownloadFile.do?fileId=16&fileSeq=2">반도체 제조업의 환경오염방지 및 통합관리를 위한 최적가용기법 기준서.pdf</a></html>'''.encode(),content_type="text/html",disposition="",url="https://official.example/board/664")\n            pdf=FakeResponse(body=b"%PDF-kbref",content_type="application/pdf",disposition='attachment; filename="kbref.pdf"',url="https://official.example/jfile/readDownloadFile.do?fileId=16&fileSeq=2")\n            session=unittest.mock.MagicMock(); session.get.side_effect=[page,pdf]\n            with patch("corporate_docs_collect.requests.Session",return_value=session):\n                status=collect(evidence,profile,out)\n            self.assertEqual(status["downloaded"],1)\n            self.assertEqual(status["failed"],0)\n            rows=list(csv.DictReader((out/"document_index.csv").open(encoding="utf-8-sig")))\n            self.assertEqual(rows[0]["collection_status"],"DOWNLOADED")\n            self.assertIn("readDownloadFile.do",rows[0]["source_url"])\n            self.assertIn("source_selection=DISCOVERED_ATTACHMENT",rows[0]["notes"])\n            attempts=list(csv.DictReader((out/"download_attempts.csv").open(encoding="utf-8-sig")))\n            self.assertEqual(attempts[0]["source_role"],"DISCOVERED_ATTACHMENT")\n\n'''
if anchor not in t:
    raise SystemExit('test anchor not found')
t = t.replace(anchor, new_test + anchor, 1)
test.write_text(t, encoding='utf-8')

# Correct Samsung BAT evidence: landing page is official provenance, expected artifact is the PDF attachment.
p = Path('requests/document_evidence.json')
data = json.loads(p.read_text(encoding='utf-8'))
data['discovery_scope']['scope_note'] = '삼성전자 Digital Library Planet 환경 정책·문서와 삼성반도체 DS 공식 환경/SHE 페이지 및 국내 핵심 생산사업장 5개(기흥·화성·평택·천안·온양)를 중심으로 한다. 수원 SAIT는 정책·연구거점 보조근거로만 보존한다. 제품별 LCA, 개별 국가 제품 규제 선언서, 비환경 People/Principle 문서는 본 환경관리 학습 수집 범위에서 제외한다.'
for d in data.get('documents', []):
    if d.get('document_id') == 'NIER_SEMICONDUCTOR_KBREF_2019':
        d['expected_extension'] = 'pdf'
        d['attachment_discovery'] = {
            'match_terms': ['반도체', '최적가용기법', '기준서'],
            'same_host_only': True
        }
        d['notes'] = 'Official NIER/IEPS K-BREF landing page. Collector must resolve and validate the same-host PDF attachment; landing-page HTML alone is not accepted as the technical full text.'
for g in data.get('gaps', []):
    if g.get('gap_id') == 'SOURCE_NATIVE_SITE_VARIANTS_REQUIRE_POST_COLLECTION_MATCHING':
        g['reason'] = '사업장명 표기가 소스별로 달라 핵심 생산사업장 5개 Identity 기준으로 결과를 재필터링한다. 수원 SAIT는 보조 후보로만 보존한다.'
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

print('patched generic official attachment discovery and Samsung K-BREF evidence')
