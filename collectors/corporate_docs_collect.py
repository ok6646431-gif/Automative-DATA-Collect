import argparse, csv, hashlib, json, mimetypes, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}
BLOCKED_EXTENSIONS = {"exe", "msi", "bat", "cmd", "ps1", "sh", "scr", "com", "dll", "jar", "apk"}
ALLOWED_EXTENSIONS = {"pdf", "html", "htm", "txt", "csv", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx"}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
FIELDS = [
    "document_id", "company_id", "canonical_site_id", "site_name_raw", "source_key", "document_type",
    "document_category", "importance", "title", "report_year", "coverage_start", "coverage_end",
    "publication_date", "original_filename", "stored_path", "source_locator", "source_url", "retrieved_at",
    "bytes", "sha256", "content_type", "verification_status", "collection_status", "notes"
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


def content_disposition_filename(header):
    header = str(header or "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r"filename=\"?([^\";]+)", header, re.I)
    return unquote(m.group(1).strip()) if m else ""


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


def is_http_url(value):
    try:
        return urlparse(str(value or "")).scheme in {"http", "https"}
    except Exception:
        return False


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
    """Visit a verified source page first when it is a distinct HTTP locator.

    Some institutional download endpoints require cookies and/or a Referer established
    by the public source page. Preflight failure is non-fatal; the download itself is
    still attempted and independently validated.
    """
    locator = str(doc.get("source_locator") or "")
    if not is_http_url(locator) or locator == source_url:
        return {}
    try:
        with session.get(locator, timeout=(8, 30), allow_redirects=True) as r:
            r.raise_for_status()
            return {"Referer": r.url}
    except Exception:
        return {"Referer": locator}


def download_one(session, doc, target, total_bytes):
    url = str(doc.get("source_url") or "")
    headers = preflight(session, doc, url)
    last_exc = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with session.get(url, stream=True, timeout=(8, 60), allow_redirects=True, headers=headers) as r:
                r.raise_for_status()
                length = int(r.headers.get("Content-Length") or 0)
                if length and length > MAX_FILE_BYTES:
                    raise ValueError(f"declared file size exceeds {MAX_FILE_BYTES} bytes")
                count = 0
                with target.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
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
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(0.5 * attempt)
    raise last_exc


def collect(evidence_path, profile_path, out_dir="output/CORP_DOCS"):
    out = Path(out_dir); raw = out / "raw_documents"; raw.mkdir(parents=True, exist_ok=True)
    profile = read_json(profile_path, {}) or {}; company_id = str(profile.get("company_id") or "")
    expected_request = str(profile.get("request_id") or "")
    evidence = read_json(evidence_path, None)
    rows = []; gaps = []; downloaded = failed = skipped = total_bytes = 0
    status = {"source_key": "CORP_DOCS", "status": "RUNNING", "request_id": expected_request}
    if evidence is None:
        status.update({"status": "NOT_RUN", "documents_declared": 0, "downloaded": 0, "failed": 0, "skipped": 0})
        write_index(out / "document_index.csv", rows)
        (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status
    supplied_request = str(evidence.get("request_id") or "")
    if not expected_request or supplied_request != expected_request:
        status.update({"status": "INVALID_SCOPE", "supplied_request_id": supplied_request, "documents_declared": len(evidence.get("documents", []) or []), "downloaded": 0, "failed": 0, "skipped": len(evidence.get("documents", []) or [])})
        for doc in evidence.get("documents", []) or []:
            rows.append(blank_row(doc, company_id, "SKIPPED_SCOPE_MISMATCH", f"expected_request_id={expected_request}; supplied_request_id={supplied_request}"))
        write_index(out / "document_index.csv", rows)
        (out / "discovery_gaps.json").write_text(json.dumps(evidence.get("gaps", []) or [], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status
    gaps = evidence.get("gaps", []) or []
    session = requests.Session(); session.headers.update({"User-Agent": UA})
    for doc in evidence.get("documents", []) or []:
        verification = str(doc.get("verification_status") or "UNVERIFIED")
        if verification not in STRONG_VERIFICATION:
            skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_UNVERIFIED", "Only VERIFIED/SOURCE_VERIFIED document evidence is downloaded.")); continue
        url = str(doc.get("source_url") or "")
        if not is_http_url(url):
            skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_UNSAFE_URL", "Only http/https document locators are allowed.")); continue
        try:
            # Filename/type decisions are made from evidence first; the response is
            # validated after download so a server-side HTML error page can never be
            # accepted merely because the URL or expected extension says '.pdf'.
            expected = str(doc.get("expected_extension") or "").lower().lstrip(".")
            if expected in BLOCKED_EXTENSIONS or (expected and expected not in ALLOWED_EXTENSIONS):
                skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_FILE_TYPE", f"extension={expected or 'unknown'}")); continue
            year = safe(doc.get("report_year") or "UNDATED"); dtype = safe(doc.get("document_type") or "OTHER_OFFICIAL_DOCUMENT")
            target_dir = raw / dtype / year; target_dir.mkdir(parents=True, exist_ok=True)
            provisional_name = safe(doc.get("title") or doc.get("document_id") or "document") + (("." + expected) if expected else "")
            provisional_target = target_dir / f"{safe(doc.get('document_id'))}_{safe(provisional_name)}"
            r, count, ctype = download_one(session, doc, provisional_target, total_bytes)
            name = remote_filename(doc, r); ext = infer_extension(doc, r, name)
            if ext in BLOCKED_EXTENSIONS or (ext and ext not in ALLOWED_EXTENSIONS):
                provisional_target.unlink(missing_ok=True)
                skipped += 1; rows.append(blank_row(doc, company_id, "SKIPPED_FILE_TYPE", f"extension={ext or 'unknown'}")); continue
            if not Path(name).suffix and ext:
                name += "." + ext
            final_target = target_dir / f"{safe(doc.get('document_id'))}_{safe(name)}"
            if final_target != provisional_target:
                provisional_target.replace(final_target)
            total_bytes += count
            row = blank_row(doc, company_id, "DOWNLOADED")
            row.update({"original_filename": name, "stored_path": str(final_target), "retrieved_at": datetime.now(timezone.utc).isoformat(), "bytes": count, "sha256": sha256(final_target), "content_type": ctype})
            rows.append(row); downloaded += 1
        except Exception as exc:
            failed += 1; rows.append(blank_row(doc, company_id, "DOWNLOAD_FAILED", f"{type(exc).__name__}: {exc}"))
    declared = len(evidence.get("documents", []) or [])
    if downloaded:
        final = "DATA_FOUND" if failed == 0 else "PARTIAL_DOWNLOAD"
    elif declared == 0:
        final = "NO_DOCUMENTS_DECLARED"
    else:
        final = "NO_DOCUMENT_DOWNLOADED"
    status.update({"status": final, "discovery_status": str(evidence.get("discovery_status") or "UNKNOWN"), "documents_declared": declared, "downloaded": downloaded, "failed": failed, "skipped": skipped, "gaps": len(gaps), "bytes": total_bytes})
    write_index(out / "document_index.csv", rows)
    (out / "discovery_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return status


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("evidence", nargs="?", default="requests/document_evidence.json"); ap.add_argument("profile", nargs="?", default="requests/runtime/company_profile.generated.json")
    args = ap.parse_args(); collect(args.evidence, args.profile)
    return 0


if __name__ == "__main__": sys.exit(main())
