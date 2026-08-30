"""Post-collection completeness audit for public sources and official documents.

This module answers a narrower question than the analytical coverage layer:
"Did we actually query every selected period and retain every verified artifact that
we said we would collect?"  A successful query with no disclosed row is recorded as
NO_DATA_CONFIRMED; an unqueried/failed period is never silently treated as no data.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

try:
    from .request_builder import build as build_request
except ImportError:
    from request_builder import build as build_request

STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}
TERMINAL_FAILURES = {
    "REMOTE_HOST_UNREACHABLE", "REQUEST_OR_PARSE_FAILED", "CONFIG_ERROR",
    "COLLECTION_FAILED_RETRY_EXHAUSTED", "INVALID_SCOPE",
}
INCOMPLETE_STATES = {
    "UNQUERIED_PERIOD", "QUERY_FAILED", "SOURCE_FAILED", "ARTIFACT_INCOMPLETE",
    "DOCUMENT_DOWNLOAD_FAILED", "DOCUMENT_FILE_MISSING", "DOCUMENT_DISCOVERY_MISSING",
    "DOCUMENT_DISCOVERY_PARTIAL", "DOCUMENT_EVIDENCE_MISSING",
}
ANNUAL_DOCUMENT_TYPES = {
    "SUSTAINABILITY_REPORT", "ESG_REPORT", "ENVIRONMENTAL_REPORT",
    "ANNUAL_ENVIRONMENT_REPORT", "ANNUAL_SUSTAINABILITY_REPORT",
}
VALIDATION_FIELDS = [
    "validation_id", "company_id", "object_type", "object_key", "issue_type", "severity",
    "detected_by", "evidence", "recommended_action", "status", "resolved_by", "resolved_at", "notes",
]
CSV_FIELDS = [
    "source", "period_kind", "period", "expected", "query_state", "data_present",
    "completeness_state", "evidence", "user_note",
]
QUARTERS = ["1분기", "2분기", "3분기", "4분기"]


def safe(value):
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", str(value or "")).strip("_")


def collector_term_key(source, value):
    """Mirror each collector's on-disk search-term filename normalization.

    Query completeness is checked against retained raw responses. PRTR and
    SOOSIRO intentionally strip punctuation from their filenames, while
    ENV-INFO and Chemical Statistics preserve dot/underscore/hyphen. Keeping
    this mapping explicit prevents false UNQUERIED_PERIOD results when the
    auditor and collector sanitize the same exact search term differently.
    """
    if source in {"PRTR", "SOOSIRO_WATER"}:
        return re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(value or "")).strip("_")
    return safe(value)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def read_csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_csv(path, rows, fields=CSV_FIELDS):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def stable_id(prefix, *parts, n=12):
    raw = "|".join("" if x is None else str(x) for x in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:n].upper()


def as_year(value):
    try:
        y = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return y if 1900 <= y <= 2100 else None


def years_in(start, end):
    a = as_year(start); b = as_year(end)
    return list(range(a, b + 1)) if a is not None and b is not None and a <= b else []


def row(source, kind, period, state, *, query_state="", data=False, evidence="", note=""):
    return {
        "source": source, "period_kind": kind, "period": str(period), "expected": "Y",
        "query_state": query_state, "data_present": "Y" if data else "N",
        "completeness_state": state, "evidence": evidence, "user_note": note,
    }


def terms_for_year(cfg, year):
    by_year = cfg.get("search_terms_by_year") or {}
    values = by_year.get(str(year))
    if values:
        return list(dict.fromkeys(str(x) for x in values if str(x).strip()))
    raw = cfg.get("search_terms") or []
    out = []
    for item in raw:
        if isinstance(item, dict):
            ys = as_year(item.get("year_start")); ye = as_year(item.get("year_end"))
            if ys is not None and year < ys: continue
            if ye is not None and year > ye: continue
            value = item.get("term")
        else:
            value = item
        if value and str(value) not in out:
            out.append(str(value))
    return out


def error_years(path, prefixes):
    p = Path(path); out = set()
    if not p.exists(): return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] in prefixes:
            y = as_year(parts[1])
            if y is not None: out.add(y)
    return out


def discovery_years(path, fields):
    out = set()
    for r in read_csv(path):
        for field in fields:
            y = as_year(r.get(field))
            if y is not None:
                out.add(y); break
    return out


def query_row(source, year, complete, failed, data, evidence):
    if complete and not failed:
        if data:
            return row(source, "YEAR", year, "DATA_PRESENT", query_state="COMPLETE", data=True, evidence=evidence)
        return row(source, "YEAR", year, "NO_DATA_CONFIRMED", query_state="COMPLETE", data=False,
                   evidence=evidence, note="정상 조회했으나 해당 연도 공개자료가 확인되지 않음")
    if failed:
        return row(source, "YEAR", year, "QUERY_FAILED", query_state="FAILED", data=data, evidence=evidence,
                   note="해당 연도 조회 실패가 있어 자료 없음으로 판정하지 않음")
    return row(source, "YEAR", year, "UNQUERIED_PERIOD", query_state="MISSING", data=data, evidence=evidence,
               note="선택 기간인데 조회 완료 증거가 없음")


def audit_envinfo(output, cfg):
    source = "ENVINFO"; root = output/source; status = read_json(root/"status.json", {}) or {}
    data_years = discovery_years(root/"discovery.csv", ["year"]); rows = []
    for year in years_in(cfg.get("start_year"), cfg.get("end_year")):
        terms = terms_for_year(cfg, year)
        files = [root/"raw_search"/f"{year}_{year}_{safe(term)}_p1.json" for term in terms]
        complete = bool(terms) and all(p.exists() and p.stat().st_size > 0 for p in files)
        failed = status.get("status") in TERMINAL_FAILURES and not complete
        rows.append(query_row(source, year, complete, failed, year in data_years,
                              f"terms={len(terms)}; page1={sum(p.exists() for p in files)}; status={status.get('status')}"))
    discovered = int(status.get("rows") or 0); detail_ok = int(status.get("detail_ok") or 0)
    if cfg.get("collect_details", True) and discovered and detail_ok != discovered:
        rows.append(row(source, "ARTIFACT", "DETAILS", "ARTIFACT_INCOMPLETE", query_state="COMPLETE",
                        data=detail_ok > 0, evidence=f"discovery_rows={discovered}; detail_ok={detail_ok}; detail_fail={status.get('detail_fail',0)}",
                        note="검색된 사업장-연도 중 상세 원문이 전부 확보되지 않음"))
    if cfg.get("collect_attachments", True) and int(status.get("attachment_fail") or 0) > 0:
        rows.append(row(source, "ARTIFACT", "ATTACHMENTS", "ARTIFACT_INCOMPLETE", query_state="COMPLETE", data=True,
                        evidence=f"discovered={status.get('attachments_discovered',0)}; downloaded={status.get('attachment_ok',0)}; failed={status.get('attachment_fail',0)}",
                        note="발견한 첨부자료 중 다운로드 실패가 있음"))
    return rows


def audit_prtr(output, cfg):
    source = "PRTR"; root = output/source; status = read_json(root/"status.json", {}) or {}
    data_years = discovery_years(root/"discovery.csv", ["search_year"])
    failures = error_years(root/"errors.log", {"SEARCH"}); rows = []
    for year in years_in(cfg.get("start_year"), cfg.get("end_year")):
        terms = terms_for_year(cfg, year)
        files = [root/"raw_search"/f"{year}_{collector_term_key(source, term)}_p1.html" for term in terms]
        complete = bool(terms) and all(p.exists() and p.stat().st_size > 0 for p in files)
        failed = year in failures or (status.get("status") in TERMINAL_FAILURES and not complete)
        rows.append(query_row(source, year, complete, failed, year in data_years,
                              f"terms={len(terms)}; page1={sum(p.exists() for p in files)}; search_error={year in failures}; status={status.get('status')}"))
    discovered = int(status.get("rows") or 0); detail_ok = int(status.get("detail_ok") or 0)
    if cfg.get("collect_details", True) and discovered and detail_ok != discovered:
        rows.append(row(source, "ARTIFACT", "DETAILS", "ARTIFACT_INCOMPLETE", query_state="COMPLETE",
                        data=detail_ok > 0, evidence=f"discovery_rows={discovered}; detail_ok={detail_ok}; detail_fail={status.get('detail_fail',0)}",
                        note="검색된 사업장-연도 중 PRTR 상세 원문이 전부 확보되지 않음"))
    return rows


def audit_chem(output, cfg):
    source = "CHEM_STATS"; root = output/source; status = read_json(root/"status.json", {}) or {}
    data_years = discovery_years(root/"discovery.csv", ["search_year", "reportYear"])
    failures = error_years(root/"errors.log", {"DISCOVERY"}); rows = []
    for year in [as_year(x) for x in cfg.get("years", [])]:
        if year is None: continue
        terms = terms_for_year(cfg, year)
        files = [root/"raw_discovery"/f"{year}_{safe(term)}_p1.json" for term in terms]
        complete = bool(terms) and all(p.exists() and p.stat().st_size > 0 for p in files)
        failed = year in failures or (status.get("status") in TERMINAL_FAILURES and not complete)
        rows.append(query_row(source, year, complete, failed, year in data_years,
                              f"terms={len(terms)}; page1={sum(p.exists() for p in files)}; search_error={year in failures}; status={status.get('status')}"))
    discovered = int(status.get("rows") or 0); detail_ok = int(status.get("detail_ok") or 0)
    if cfg.get("collect_details", True) and discovered and detail_ok != discovered:
        rows.append(row(source, "ARTIFACT", "DETAILS", "ARTIFACT_INCOMPLETE", query_state="COMPLETE",
                        data=detail_ok > 0, evidence=f"discovery_rows={discovered}; detail_ok={detail_ok}; detail_fail={status.get('detail_fail',0)}",
                        note="검색된 사업장-연도 중 화학물질통계 상세 원문이 전부 확보되지 않음"))
    return rows


def audit_cleansys(output, cfg):
    source = "CLEANSYS_AIR"; root = output/source; status = read_json(root/"status.json", {}) or {}
    data_years = {as_year(r.get("examin_year")) for r in read_jsonl(root/"annual_rows.jsonl")}
    data_years.discard(None); errors = status.get("errors") or []; terminal = status.get("status") in TERMINAL_FAILURES
    rows = []
    for year in years_in(cfg.get("start_year"), cfg.get("end_year")):
        if terminal or errors:
            rows.append(query_row(source, year, False, True, year in data_years,
                                  f"range={cfg.get('start_year')}..{cfg.get('end_year')}; candidate_errors={len(errors)}; status={status.get('status')}"))
        else:
            rows.append(query_row(source, year, True, False, year in data_years,
                                  f"range_query_complete; candidates={status.get('candidate_count',0)}; status={status.get('status')}"))
    return rows


def audit_soosiro(output, cfg):
    source = "SOOSIRO_WATER"; root = output/source; status = read_json(root/"status.json", {}) or {}
    annual_data = {as_year(r.get("YEAR", r.get("year"))) for r in read_jsonl(root/"annual_rows.jsonl")}; annual_data.discard(None)
    annual_fail = error_years(root/"errors.log", {"ANNUAL", "ANNUAL_FACT"}); rows = []
    annual_state = {}
    for year in [as_year(x) for x in cfg.get("annual_years", [])]:
        if year is None: continue
        terms = terms_for_year(cfg, year)
        term_files = [root/"raw_annual"/f"{year}_{collector_term_key(source, term)}.json" for term in terms]
        complete = bool(terms) and all(p.exists() and p.stat().st_size > 0 for p in term_files)
        failed = year in annual_fail or (status.get("status") in TERMINAL_FAILURES and not complete)
        r = query_row(source, year, complete, failed, year in annual_data,
                      f"annual_terms={len(terms)}; term_responses={sum(p.exists() for p in term_files)}; annual_error={year in annual_fail}; status={status.get('status')}")
        rows.append(r); annual_state[year] = r["completeness_state"]

    candidates = read_json(root/"fact_candidates.json", []) or []
    fact_codes = sorted({str(x.get("FACT_CODE") or "") for x in candidates if x.get("FACT_CODE")})
    daily_data = {as_year(r.get("query_year", r.get("YEAR", r.get("year")))) for r in read_jsonl(root/"daily_rows.jsonl")}; daily_data.discard(None)
    daily_fail = error_years(root/"errors.log", {"DAILY"})
    for year in [as_year(x) for x in cfg.get("daily_years", [])]:
        if year is None: continue
        if not fact_codes:
            complete = annual_state.get(year) in {"DATA_PRESENT", "NO_DATA_CONFIRMED"}
            failed = annual_state.get(year) in {"QUERY_FAILED", "UNQUERIED_PERIOD"}
            state_row = query_row("SOOSIRO_WATER_DAILY", year, complete, failed, False,
                                  f"fact_codes=0; annual_state={annual_state.get(year,'UNKNOWN')}")
            rows.append(state_row); continue
        expected_files = [root/"raw_daily"/f"{year}_{fc}_{q}.json" for fc in fact_codes for q in QUARTERS]
        complete = all(p.exists() and p.stat().st_size > 0 for p in expected_files)
        failed = year in daily_fail or (status.get("status") in TERMINAL_FAILURES and not complete)
        rows.append(query_row("SOOSIRO_WATER_DAILY", year, complete, failed, year in daily_data,
                              f"fact_codes={len(fact_codes)}; expected_quarters={len(expected_files)}; responses={sum(p.exists() for p in expected_files)}; daily_error={year in daily_fail}"))
    return rows


def public_rows(output, request):
    cfg = (request or {}).get("sources") or {}; rows = []
    if "ENVINFO" in cfg: rows += audit_envinfo(output, cfg["ENVINFO"])
    if "PRTR" in cfg: rows += audit_prtr(output, cfg["PRTR"])
    if "CHEM_STATS" in cfg: rows += audit_chem(output, cfg["CHEM_STATS"])
    if "CLEANSYS_AIR" in cfg: rows += audit_cleansys(output, cfg["CLEANSYS_AIR"])
    if "SOOSIRO_WATER" in cfg: rows += audit_soosiro(output, cfg["SOOSIRO_WATER"])
    return rows


def gap_resolves(gap, dtype, year):
    if not isinstance(gap, dict): return False
    if str(gap.get("verification_status") or "").upper() not in STRONG_VERIFICATION: return False
    state = str(gap.get("resolution") or gap.get("status") or gap.get("gap_status") or "").upper()
    if state not in {"NOT_PUBLISHED", "NO_PUBLIC_DOCUMENT", "NO_DATA_CONFIRMED"}: return False
    target = str(gap.get("document_type") or "").upper()
    if target and target != dtype: return False
    y = as_year(gap.get("year") or gap.get("report_year"))
    if y is not None: return y == year
    return year in years_in(gap.get("coverage_start"), gap.get("coverage_end"))


def document_rows(package, profile, evidence):
    docs_root = package/"output"/"CORP_DOCS"; index = read_csv(docs_root/"document_index.csv")
    by_id = {str(x.get("document_id") or ""): x for x in index}; rows = []
    documents = (evidence or {}).get("documents") or []; gaps = (evidence or {}).get("gaps") or []
    strong_docs = [d for d in documents if str(d.get("verification_status") or "").upper() in STRONG_VERIFICATION]

    for doc in strong_docs:
        did = str(doc.get("document_id") or ""); idx = by_id.get(did)
        if idx is None:
            rows.append(row("CORP_DOCS", "DOCUMENT", did or doc.get("title"), "DOCUMENT_EVIDENCE_MISSING",
                            query_state="MISSING", evidence=f"type={doc.get('document_type')}; year={doc.get('report_year')}",
                            note="검증된 수집대상 문서가 document_index에 없음")); continue
        status = str(idx.get("collection_status") or "").upper(); stored = str(idx.get("stored_path") or "")
        file_ok = bool(stored and (package/stored).exists())
        if status == "DOWNLOADED" and file_ok:
            rows.append(row("CORP_DOCS", "DOCUMENT", did, "DATA_PRESENT", query_state="COMPLETE", data=True,
                            evidence=f"type={doc.get('document_type')}; year={doc.get('report_year')}; path={stored}"))
        elif status == "DOWNLOADED":
            rows.append(row("CORP_DOCS", "DOCUMENT", did, "DOCUMENT_FILE_MISSING", query_state="COMPLETE", data=False,
                            evidence=f"declared_path={stored}", note="다운로드 성공 기록은 있으나 패키지에 실제 파일이 없음"))
        else:
            rows.append(row("CORP_DOCS", "DOCUMENT", did, "DOCUMENT_DOWNLOAD_FAILED", query_state=status or "UNKNOWN", data=False,
                            evidence=f"type={doc.get('document_type')}; year={doc.get('report_year')}; collection_status={status}",
                            note="검증된 공식문서 다운로드가 완료되지 않음"))

    discovery_status = str((evidence or {}).get("discovery_status") or "").upper()
    if discovery_status and discovery_status not in {"COMPLETE", "VERIFIED_COMPLETE", "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"}:
        rows.append(row("CORP_DOCS", "DISCOVERY", "OFFICIAL_DOCUMENT_SCOPE", "DOCUMENT_DISCOVERY_PARTIAL",
                        query_state=discovery_status, data=bool(strong_docs), evidence=f"discovery_status={discovery_status}",
                        note="공식문서 탐색 자체가 완결 상태로 확인되지 않아 미발견 문서를 없다고 간주하지 않음"))

    requested = (profile or {}).get("requested_history_window") or {}
    start = as_year(requested.get("start_year")); end = as_year(requested.get("end_year"))
    legal_start = as_year(((profile or {}).get("current_legal_name_active_period") or {}).get("start_year"))
    for dtype in sorted(ANNUAL_DOCUMENT_TYPES):
        declared = {as_year(d.get("report_year")): d for d in strong_docs if str(d.get("document_type") or "").upper() == dtype and as_year(d.get("report_year")) is not None}
        if not declared: continue
        series_start = start if start is not None else min(declared)
        series_end = max([x for x in [end, max(declared)] if x is not None])
        if legal_start is not None: series_start = max(series_start, legal_start)
        for year in range(series_start, series_end + 1):
            if year in declared:
                continue  # the document-level row above determines actual file completeness
            if any(gap_resolves(g, dtype, year) for g in gaps):
                rows.append(row("CORP_DOCS", dtype, year, "NO_DATA_CONFIRMED", query_state="VERIFIED_GAP", data=False,
                                evidence="explicit verified NOT_PUBLISHED/NO_PUBLIC_DOCUMENT gap",
                                note="공식적으로 미발행/미공개가 확인된 연도"))
            else:
                rows.append(row("CORP_DOCS", dtype, year, "DOCUMENT_DISCOVERY_MISSING", query_state="MISSING", data=False,
                                evidence=f"requested_history={series_start}..{series_end}; declared={sorted(declared)}",
                                note="연차 문서 시리즈의 선택 기간 중 해당 연도 문서 또는 검증된 미발행 근거가 없음"))
    return rows


def validation_for(company_id, item):
    state = item["completeness_state"]
    severity = "HIGH" if state in {"QUERY_FAILED", "SOURCE_FAILED", "ARTIFACT_INCOMPLETE", "DOCUMENT_DOWNLOAD_FAILED", "DOCUMENT_FILE_MISSING"} else "MEDIUM"
    key = f"{item['source']}:{item['period_kind']}:{item['period']}"
    action = (
        "Retry/recover the missing period or artifact. Do not label it as no data until a successful source query or verified not-published record exists."
    )
    return {
        "validation_id": stable_id("VAL_", company_id, "COLLECTION_COMPLETENESS", key, state),
        "company_id": company_id, "object_type": "COLLECTION_COMPLETENESS", "object_key": key,
        "issue_type": state, "severity": severity, "detected_by": "COLLECTION_COMPLETENESS_GATE",
        "evidence": item.get("evidence", ""), "recommended_action": action, "status": "REVIEW_REQUIRED",
        "resolved_by": "", "resolved_at": "", "notes": item.get("user_note", ""),
    }


def merge_validations(package, additions):
    q = package/"Validation_Queue.csv"; existing = read_csv(q)
    by_id = {x.get("validation_id"): x for x in existing if x.get("validation_id")}; order = [x for x in by_id]
    for item in additions:
        vid = item["validation_id"]
        if vid not in by_id:
            by_id[vid] = item; order.append(vid)
    with q.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=VALIDATION_FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows([by_id[x] for x in order])
    r = package/"REVIEW_REQUIRED.json"; review = read_json(r, []) or []; seen = {x.get("validation_id") for x in review if isinstance(x, dict)}
    for item in additions:
        if item["validation_id"] not in seen:
            review.append(item); seen.add(item["validation_id"])
    r.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(review)


def audit(package_root, profile_path, request_path=None, evidence_path=None):
    package = Path(package_root); output = package/"output"
    profile = read_json(profile_path, {}) or {}
    request = read_json(request_path, {}) if request_path and Path(request_path).exists() else build_request(profile)
    request = request or {}
    evidence = read_json(evidence_path, {}) if evidence_path and Path(evidence_path).exists() else {}
    rows = public_rows(output, request) + document_rows(package, profile, evidence or {})
    incomplete = [x for x in rows if x["completeness_state"] in INCOMPLETE_STATES]
    no_data = [x for x in rows if x["completeness_state"] == "NO_DATA_CONFIRMED"]
    complete = [x for x in rows if x["completeness_state"] in {"DATA_PRESENT", "NO_DATA_CONFIRMED"}]

    write_csv(package/"Collection_Completeness.csv", rows)
    write_csv(package/"Collection_No_Data.csv", no_data)
    summary = {
        "schema_version": "1.0", "status": "REVIEW_REQUIRED" if incomplete else "COMPLETE",
        "checked_items": len(rows), "complete_items": len(complete), "incomplete_items": len(incomplete),
        "no_data_confirmed_items": len(no_data),
        "incomplete_keys": [f"{x['source']}:{x['period_kind']}:{x['period']}:{x['completeness_state']}" for x in incomplete],
        "no_data_confirmed": [{"source":x["source"], "period_kind":x["period_kind"], "period":x["period"], "note":x["user_note"]} for x in no_data],
        "principles": [
            "Every selected period must have successful query evidence or an explicit failure state.",
            "A successful query with no disclosed row is NO_DATA_CONFIRMED and is reported separately.",
            "Every strongly verified declared official document must have a real delivered file.",
            "Annual official-document series must cover the full requested history window; latest-N is not sufficient.",
        ],
    }
    (package/"Collection_Completeness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    integration = read_json(package/"Integration_Summary.json", {}) or {}
    company_id = str(integration.get("company_id") or profile.get("company_id") or stable_id("COMP_", profile.get("company_display_name")))
    additions = [validation_for(company_id, x) for x in incomplete]
    review_count = merge_validations(package, additions) if additions else len(read_json(package/"REVIEW_REQUIRED.json", []) or [])
    integration["collection_completeness"] = summary; integration["validation_queue"] = len(read_csv(package/"Validation_Queue.csv"))
    (package/"Integration_Summary.json").write_text(json.dumps(integration, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = read_json(package/"Master_Manifest.json", {}) or {}
    manifest["collection_completeness"] = summary
    if incomplete and manifest.get("package_health") == "PASS": manifest["package_health"] = "DEGRADED"
    manifest["review_count"] = review_count; manifest["validation"] = "REVIEW_REQUIRED" if review_count else "PASS"
    (package/"Master_Manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser(description="Audit exact selected-period and official-document collection completeness")
    ap.add_argument("--package", default="assembled")
    ap.add_argument("--profile", default="requests/runtime/company_profile.generated.json")
    ap.add_argument("--request", default="requests/current.generated.json")
    ap.add_argument("--documents", default="requests/document_evidence.json")
    args = ap.parse_args()
    result = audit(args.package, args.profile, args.request, args.documents)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
