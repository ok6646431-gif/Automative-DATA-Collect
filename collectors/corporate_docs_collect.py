import argparse, csv, hashlib, json, mimetypes, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse, urljoin
from html.parser import HTMLParser

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}
BLOCKED_EXTENSIONS = {"exe", "msi", "bat", "cmd", "ps1", "sh", "scr", "com", "dll", "jar", "apk"}
ALLOWED_EXTENSIONS = {"pdf", "html", "htm", "txt", "csv", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx"}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
# Keep each source attempt bounded. A document may declare separately verified
# fallback_sources; the collector tries them only after the primary source fails.
DOWNLOAD_ATTEMPTS = 2
PREFLIGHT_TIMEOUT = (5, 10)
DOWNLOAD_TIMEOUT = (8, 25)
ATTACHMENT_DISCOVERY_TIMEOUT = (15, 30)
# requests' read timeout is an inactivity timeout, not a total transfer deadline.
# Bound each source candidate so slow-drip servers cannot monopolize a workflow.
MAX_DOCUMENT_WALL_SECONDS = 120.0
PREFLIGHT_CACHE = {}
FIELDS = [
    "document_id", "company_id", "canonical_site_id", "site_name_raw", "source_key", "document_type",
    "document_category", "importance", "title", "report_year", "coverage_start", "coverage_end",
    "publication_date", "original_filename", "stored_path", "source_locator", "source_url", "retrieved_at",
    "bytes", "sha256", "content_type", "verification_status", "collection_status", "notes"
]
ATTEMPT_FIELDS = [
    "document_id", "source_order", "source_role", "source_url", "source_locator", "verification_status",
    "attempt_status", "error", "bytes", "content_type"
]


def safe(value):
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", str(value or "")).strip(" ._")
    return text[:160] or "document"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def repair_header_filename(value):
    """Repair UTF-8 filename bytes that requests decoded as ISO-8859-1."""
    text = str(value or "")
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if fixed == text:
        return text
    old_controls = sum(0x80 <= ord(ch) <= 0x9F for ch in text)
    new_controls = sum(0x80 <= ord(ch) <= 0x9F for ch in fixed)
    old_hangul = sum("가" <= ch <= "힣" for ch in text)
    new_hangul = sum("가" <= ch <= "힣" for ch in fixed)
    return fixed if new_hangul > old_hangul or new_controls < old_controls else text


def content_disposition_filename(header):
    header = str(header or "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.I)
    if m:
        return repair_header_filename(unquote(m.group(1).strip().strip('"')))
    m = re.search(r"filename=\"?([^\";]+)", header, re.I)
    return repair_header_filename(unquote(m.group(1).strip())) if m else ""


def infer_extension(doc, response, filename):
    expected = str(doc.get("expected_extension") or "").lower().lstrip(".")
    if expected:
        return expected
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    ctype = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ctype) or ""
    return guessed.lstrip(".")


def remote_filename(doc, response):
    cd = content_disposition_filename(response.headers.get("Content-Disposition"))
    if cd:
        return cd
    path_name = unquote(Path(urlparse(str(doc.get("source_url") or "")).path).name)
    if path_name and "." in path_name:
        return path_name
    expected = str(doc.get("expected_extension") or "").lstrip(".")
    title = safe(doc.get("title") or doc.get("document_id") or "document")
    return title + (("." + expected) if expected else "")


def blank_row(doc, company_id, status, notes=""):
    return {
        "document_id": str(doc.get("document_id") or ""), "company_id": company_id,
        "canonical_site_id": str(doc.get("canonical_site_id") or ""), "site_name_raw": str(doc.get("site_name_raw") or ""),
        "source_key": "CORP_DOCS", "document_type": str(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT"),
        "document_category": str(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT"),
        "importance": str(doc.get("importance") or "UNCLASSIFIED"), "title": str(doc.get("title") or ""),
        "report_year": str(doc.get("report_year") or ""), "coverage_start": str(doc.get("coverage_start") or ""),
        "coverage_end": str(doc.get("coverage_end") or ""), "publication_date": str(doc.get("publication_date") or ""),
        "original_filename": "", "stored_path": "", "source_locator": str(doc.get("source_locator") or doc.get("source_url") or ""),
        "source_url": str(doc.get("source_url") or ""), "retrieved_at": "", "bytes": "", "sha256": "",
        "content_type": "", "verification_status": str(doc.get("verification_status") or "UNVERIFIED"),
        "collection_status": status, "notes": notes or str(doc.get("notes") or "")
    }


def write_index(path, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def write_attempts(path, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ATTEMPT_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def is_http_url(value):
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
    return re.sub(r"\s+", "", str(value or "")).lower()


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
    body = None; resolved_page = page_url
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            with session.get(page_url, timeout=ATTACHMENT_DISCOVERY_TIMEOUT, allow_redirects=True) as r:
                r.raise_for_status()
                body = getattr(r, "text", None)
                if body is None:
                    raw = getattr(r, "body", b"")
                    body = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
                resolved_page = str(getattr(r, "url", None) or page_url)
                PREFLIGHT_CACHE[page_url] = {"Referer": resolved_page}
                break
        except Exception:
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                time.sleep(1.0)
    if body is None:
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


def validate_payload(expected_ext, content_type, path):
    """Reject obvious error/login HTML masquerading as declared binary documents."""
    expected = str(expected_ext or "").lower().lstrip(".")
    ctype = str(content_type or "").split(";")[0].strip().lower()
    with Path(path).open("rb") as f:
        head = f.read(4096).lstrip()
    head_lower = head.lower()
    looks_html = (
        ctype in {"text/html", "application/xhtml+xml"}
        or head_lower.startswith(b"<!doctype html")
        or head_lower.startswith(b"<html")
        or b"<html" in head_lower[:512]
    )
    if expected == "pdf":
        if looks_html or not head.startswith(b"%PDF-"):
            raise ValueError(f"expected PDF payload but received content_type={ctype or 'unknown'}")
    elif expected in {"html", "htm"}:
        if not looks_html:
            raise ValueError(f"expected HTML payload but received content_type={ctype or 'unknown'}")
    elif expected in {"png", "jpg", "jpeg", "gif", "webp"} and looks_html:
        raise ValueError(f"expected image payload but received HTML content_type={ctype or 'unknown'}")
    elif expected in {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx"} and looks_html:
        raise ValueError(f"expected office-document payload but received HTML content_type={ctype or 'unknown'}")


def preflight(session, doc, source_url):
    """Visit a verified source page once per locator to establish cookies/Referer."""
    locator = str(doc.get("source_locator") or "")
    if not is_http_url(locator) or locator == source_url:
        return {}
    if locator in PREFLIGHT_CACHE:
        return dict(PREFLIGHT_CACHE[locator])
    try:
        with session.get(locator, timeout=PREFLIGHT_TIMEOUT, allow_redirects=True) as r:
            r.raise_for_status()
            headers = {"Referer": r.url}
    except Exception:
        headers = {"Referer": locator}
    PREFLIGHT_CACHE[locator] = headers
    return dict(headers)


def download_one(session, doc, target, total_bytes):
    url = str(doc.get("source_url") or "")
    headers = preflight(session, doc, url)
    last_exc = None
    deadline = time.monotonic() + MAX_DOCUMENT_WALL_SECONDS
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last_exc = TimeoutError(f"document wall-clock budget exceeded ({MAX_DOCUMENT_WALL_SECONDS:.0f}s)")
            break
        connect_timeout = max(1.0, min(float(DOWNLOAD_TIMEOUT[0]), remaining))
        read_timeout = max(1.0, min(float(DOWNLOAD_TIMEOUT[1]), remaining))
        try:
            with session.get(url, stream=True, timeout=(connect_timeout, read_timeout), allow_redirects=True, headers=headers) as r:
                r.raise_for_status()
                length = int(r.headers.get("Content-Length") or 0)
                if length and length > MAX_FILE_BYTES:
                    raise ValueError(f"declared file size exceeds {MAX_FILE_BYTES} bytes")
                count = 0
                with target.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if time.monotonic() > deadline:
                            raise TimeoutError(f"document wall-clock budget exceeded ({MAX_DOCUMENT_WALL_SECONDS:.0f}s)")
                        if not chunk:
                            continue
                        count += len(chunk)
                        if count > MAX_FILE_BYTES or total_bytes + count > MAX_TOTAL_BYTES:
                            raise ValueError("document collection size safety limit exceeded")
                        f.write(chunk)
                if count == 0:
                    raise ValueError("zero-byte document response")
                ctype = str(r.headers.get("Content-Type") or "").split(";")[0]
                validate_payload(doc.get("expected_extension"), ctype, target)
                return r, count, ctype
        except Exception as exc:
            last_exc = exc
            target.unlink(missing_ok=True)
            if attempt < DOWNLOAD_ATTEMPTS and time.monotonic() < deadline:
                time.sleep(min(0.5 * attempt, max(0.0, deadline - time.monotonic())))
    raise last_exc


def source_candidates(doc):
    """Return primary then independently verified official fallback sources.

    Fallback entries may override only source-specific fields. They never change the
    document identity, report year, type, or importance declared by Discovery.
    """
    primary = dict(doc)
    primary["_source_role"] = "PRIMARY"
    primary["_source_order"] = 0
    result = [primary]
    seen = {str(primary.get("source_url") or "")}
    for idx, alt in enumerate(doc.get("fallback_sources") or [], 1):
        if not isinstance(alt, dict):
            continue
        candidate = dict(doc)
        for key in ("source_url", "source_locator", "expected_extension", "verification_status"):
            if key in alt:
                candidate[key] = alt[key]
        candidate["_source_role"] = f"FALLBACK_{idx}"
        candidate["_source_order"] = idx
        candidate["_source_note"] = str(alt.get("notes") or alt.get("source_role") or "")
        url = str(candidate.get("source_url") or "")
        if not url or url in seen:
            continue
        seen.add(url); result.append(candidate)
    return result


def attempt_row(doc, candidate, status, error="", count="", ctype=""):
    return {
        "document_id": str(doc.get("document_id") or ""),
        "source_order": candidate.get("_source_order", ""),
        "source_role": candidate.get("_source_role", ""),
        "source_url": str(candidate.get("source_url") or ""),
        "source_locator": str(candidate.get("source_locator") or candidate.get("source_url") or ""),
        "verification_status": str(candidate.get("verification_status") or "UNVERIFIED"),
        "attempt_status": status, "error": str(error or "")[:2000], "bytes": count, "content_type": ctype
    }


def collect(evidence_path, profile_path, out_dir="output/CORP_DOCS"):
    out = Path(out_dir); raw = out / "raw_documents"; raw.mkdir(parents=True, exist_ok=True)
    profile = read_json(profile_path, {}) or {}; company_id = str(profile.get("company_id") or "")
    expected_request = str(profile.get("request_id") or "")
    evidence = read_json(evidence_path, None)
    rows = []; attempts = []; gaps = []; downloaded = failed = skipped = fallback_downloaded = total_bytes = 0
    status = {"source_key": "CORP_DOCS", "status": "RUNNING", "request_id": expected_request}
    if evidence is None:
        status.update({"status": "NOT_RUN", "documents_declared": 0, "downloaded": 0, "failed": 0, "skipped": 0, "fallback_downloaded": 0})
        write_index(out / "document_index.csv", rows); write_attempts(out / "download_attempts.csv", attempts)
        (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status

    supplied_request = str(evidence.get("request_id") or "")
    if not expected_request or supplied_request != expected_request:
        docs = evidence.get("documents", []) or []
        status.update({"status": "INVALID_SCOPE", "supplied_request_id": supplied_request, "documents_declared": len(docs), "downloaded": 0, "failed": 0, "skipped": len(docs), "fallback_downloaded": 0})
        for doc in docs:
            rows.append(blank_row(doc, company_id, "SKIPPED_SCOPE_MISMATCH", f"expected_request_id={expected_request}; supplied_request_id={supplied_request}"))
        write_index(out / "document_index.csv", rows); write_attempts(out / "download_attempts.csv", attempts)
        (out / "discovery_gaps.json").write_text(json.dumps(evidence.get("gaps", []) or [], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status

    gaps = evidence.get("gaps", []) or []
    session = requests.Session(); session.headers.update({"User-Agent": UA}); PREFLIGHT_CACHE.clear()

    for doc in evidence.get("documents", []) or []:
        verification = str(doc.get("verification_status") or "UNVERIFIED")
        if verification not in STRONG_VERIFICATION:
            skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_UNVERIFIED", "Only VERIFIED/SOURCE_VERIFIED document evidence is downloaded.")); continue

        base_expected = str(doc.get("expected_extension") or "").lower().lstrip(".")
        if base_expected in BLOCKED_EXTENSIONS or (base_expected and base_expected not in ALLOWED_EXTENSIONS):
            skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_FILE_TYPE", f"extension={base_expected or 'unknown'}")); continue

        year = safe(doc.get("report_year") or "UNDATED"); dtype = safe(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT")
        target_dir = raw / dtype / year; target_dir.mkdir(parents=True, exist_ok=True)
        provisional_name = safe(doc.get("title") or doc.get("document_id") or "document") + (("." + base_expected) if base_expected else "")
        provisional_target = target_dir / f"{safe(doc.get('document_id'))}_{safe(provisional_name)}"
        errors = []; blocked_only = True; success = False

        candidates = source_candidates(doc)
        discovered = discover_attachment_candidates(session, doc)
        if discovered:
            candidates = discovered + [
                c for c in candidates
                if str(c.get("_source_role") or "").startswith("FALLBACK_")
            ]

        for candidate in candidates:
            role = str(candidate.get("_source_role") or "PRIMARY")
            candidate_verification = str(candidate.get("verification_status") or "UNVERIFIED")
            url = str(candidate.get("source_url") or "")
            if candidate_verification not in STRONG_VERIFICATION:
                attempts.append(attempt_row(doc, candidate, "SKIPPED_UNVERIFIED_SOURCE", "Fallback source is not independently verified.")); errors.append(f"{role}:unverified"); continue
            if not is_http_url(url):
                attempts.append(attempt_row(doc, candidate, "SKIPPED_UNSAFE_SOURCE", "Only http/https source URLs are allowed.")); errors.append(f"{role}:unsafe_url"); continue
            expected = str(candidate.get("expected_extension") or base_expected or "").lower().lstrip(".")
            if expected in BLOCKED_EXTENSIONS or (expected and expected not in ALLOWED_EXTENSIONS):
                attempts.append(attempt_row(doc, candidate, "SKIPPED_FILE_TYPE", f"extension={expected or 'unknown'}")); errors.append(f"{role}:blocked_extension={expected}"); continue

            blocked_only = False
            try:
                r, count, ctype = download_one(session, candidate, provisional_target, total_bytes)
                name = remote_filename(candidate, r); ext = infer_extension(candidate, r, name)
                if ext in BLOCKED_EXTENSIONS or (ext and ext not in ALLOWED_EXTENSIONS):
                    provisional_target.unlink(missing_ok=True)
                    attempts.append(attempt_row(doc, candidate, "SKIPPED_FILE_TYPE", f"response_extension={ext or 'unknown'}")); errors.append(f"{role}:blocked_response_extension={ext}"); blocked_only = True; continue
                if not Path(name).suffix and ext:
                    name += "." + ext
                final_target = target_dir / f"{safe(doc.get('document_id'))}_{safe(name)}"
                if final_target != provisional_target:
                    provisional_target.replace(final_target)
                total_bytes += count
                note_parts = [str(doc.get("notes") or ""), f"source_selection={role}"]
                if role != "PRIMARY":
                    note_parts.append(f"primary_source_url={doc.get('source_url','')}")
                    if candidate.get("_source_note"):
                        note_parts.append(f"fallback_note={candidate.get('_source_note')}")
                row = blank_row(doc, company_id, "DOWNLOADED", "; ".join(x for x in note_parts if x))
                row.update({
                    "original_filename": name, "stored_path": str(final_target), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "bytes": count, "sha256": sha256(final_target), "content_type": ctype,
                    "source_url": url, "source_locator": str(candidate.get("source_locator") or url),
                    "verification_status": candidate_verification
                })
                rows.append(row); attempts.append(attempt_row(doc, candidate, "DOWNLOADED", count=count, ctype=ctype))
                downloaded += 1; fallback_downloaded += int(role.startswith("FALLBACK_")); success = True; break
            except Exception as exc:
                provisional_target.unlink(missing_ok=True)
                msg = f"{type(exc).__name__}: {exc}"
                attempts.append(attempt_row(doc, candidate, "DOWNLOAD_FAILED", msg)); errors.append(f"{role}:{msg}")

        if success:
            continue
        if blocked_only and errors and all("blocked" in x for x in errors):
            skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_FILE_TYPE", " | ".join(errors)))
        else:
            failed += 1; rows.append(blank_row(doc, company_id, "DOWNLOAD_FAILED", " | ".join(errors) or "No usable verified source candidate."))

    declared = len(evidence.get("documents", []) or [])
    if downloaded:
        final = "DATA_FOUND" if failed == 0 else "PARTIAL_DOWNLOAD"
    elif declared == 0:
        final = "NO_DOCUMENTS_DECLARED"
    else:
        final = "NO_DOCUMENT_DOWNLOADED"
    status.update({
        "status": final, "discovery_status": str(evidence.get("discovery_status") or "UNKNOWN"),
        "documents_declared": declared, "downloaded": downloaded, "fallback_downloaded": fallback_downloaded,
        "failed": failed, "skipped": skipped, "gaps": len(gaps), "bytes": total_bytes,
        "source_attempt_rows": len(attempts)
    })
    write_index(out / "document_index.csv", rows); write_attempts(out / "download_attempts.csv", attempts)
    (out / "discovery_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return status


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("evidence", nargs="?", default="requests/document_evidence.json"); ap.add_argument("profile", nargs="?", default="requests/runtime/company_profile.generated.json")
    args = ap.parse_args(); collect(args.evidence, args.profile)
    return 0


if __name__ == "__main__": sys.exit(main())
