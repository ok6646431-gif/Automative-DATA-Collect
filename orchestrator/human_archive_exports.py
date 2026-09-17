"""Human-facing structured-source exports for Archive v1.

This module deliberately separates three states that the old user workbooks blurred:
1. rows confirmed inside requested scope,
2. rows collected for the current entity but whose site binding still needs review,
3. genuine no-data / failed collection states.

Unbound rows are visible to the user but are never promoted into the confirmed analysis
scope by this module.
"""

import csv
import json
from pathlib import Path

try:
    import xlsxwriter
except Exception:  # pragma: no cover - archive job installs it
    xlsxwriter = None


SOURCES = ("CLEANSYS_AIR", "SOOSIRO_WATER", "PRTR", "CHEM_STATS")


def _json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def _jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _source_id(row, source):
    if source == "CLEANSYS_AIR":
        return str(row.get("source_fact_code") or row.get("fact_code") or "")
    if source == "SOOSIRO_WATER":
        return str(row.get("FACT_CODE") or row.get("source_fact_code") or "")
    if source == "PRTR":
        return str(row.get("entrps_id") or "")
    if source == "CHEM_STATS":
        return str(row.get("bplcId") or "")
    return ""


def _identity_review_map(package_root, source):
    out = {}
    for row in _csv(Path(package_root) / "Source_Identity.csv"):
        if row.get("source_key") != source:
            continue
        if row.get("match_status") == "REJECTED":
            continue
        if row.get("match_status") == "REVIEW_REQUIRED" or _truthy(row.get("review_required")):
            out[str(row.get("source_site_id") or "")] = row
    return out


def _status(root, source):
    return _json(Path(root) / source / "status.json", {}) or {}


def _years(values):
    out = []
    for value in values:
        text = str(value or "").strip()
        if len(text) >= 4 and text[:4].isdigit():
            out.append(int(text[:4]))
    return sorted(set(out))


def _write_xlsx(path, sheets):
    if xlsxwriter is None:
        raise RuntimeError("xlsxwriter is required for human-facing Excel exports")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path), {"constant_memory": True})
    header = wb.add_format({"bold": True, "bg_color": "#E7E6E6", "border": 1, "align": "center", "valign": "vcenter"})
    textfmt = wb.add_format({"valign": "top"})
    wrap = wb.add_format({"valign": "top", "text_wrap": True})
    for sheet_name, rows in sheets:
        ws = wb.add_worksheet(str(sheet_name)[:31])
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        if not fields:
            fields = ["상태"]
            rows = [{"상태": "표시할 행이 없습니다. '수집상태' 시트를 확인하세요."}]
        for col, key in enumerate(fields):
            ws.write(0, col, key, header)
        for r_idx, row in enumerate(rows, 1):
            for col, key in enumerate(fields):
                value = row.get(key, "")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                ws.write(r_idx, col, value, wrap if isinstance(value, str) and len(value) > 50 else textfmt)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, max(1, len(rows)), len(fields) - 1)
        for col, key in enumerate(fields):
            maxlen = max([len(str(key))] + [len(str(row.get(key, ""))) for row in rows[:300]])
            ws.set_column(col, col, min(max(maxlen + 2, 10), 44))
    wb.close()


def _prtr_summary(row):
    return {
        "자료연도": row.get("search_year", ""),
        "원문 사업장명": row.get("company_name_raw", ""),
        "원문 주소": row.get("address_raw", ""),
        "PRTR 사업장ID": row.get("entrps_id", ""),
        "총배출량 원문값": row.get("release_total_raw", ""),
        "자가매립량 원문값": row.get("self_landfill_raw", ""),
        "총이동량 원문값": row.get("transfer_total_raw", ""),
        "원문 출처": row.get("source_url", ""),
    }


def _chem_summary(row):
    result = {
        "자료연도": row.get("search_year") or row.get("reportYear", ""),
        "해당연도 원문 사업장명": row.get("bplcNm", ""),
        "해당연도 원문 주소": row.get("locplcAdres", ""),
        "화학물질통계 사업장ID": row.get("bplcId", ""),
        "원문 업종": row.get("induty", ""),
    }
    anchor_year = row.get("identity_anchor_year", "")
    anchor_name = row.get("identity_anchor_bplcNm", "")
    anchor_address = row.get("identity_anchor_locplcAdres", "")
    if anchor_year or anchor_name or anchor_address:
        result.update({
            "동일사업장 확인기준 연도": anchor_year,
            "동일사업장 확인기준 사업장명": anchor_name,
            "동일사업장 확인기준 주소": anchor_address,
            "확인기준 설명": "해당 연도 원문에 사업장명/주소가 없을 때 동일 source ID를 확인하기 위한 별도 identity anchor이며, 해당연도 주소로 해석하지 않음",
        })
    return result


def _source_table_row(row, id_key):
    cells = list(row.get("cells") or [])
    out = {
        "자료연도": row.get("search_year", ""),
        "사업장ID": row.get(id_key, ""),
        "원문 테이블번호": row.get("table_index", ""),
        "원문 행번호": row.get("row_index", ""),
    }
    for idx, value in enumerate(cells, 1):
        out[f"원문 셀{idx}"] = value
    return out


def _clean_summary(row):
    return {
        "자료연도": row.get("examin_year", ""),
        "원문 사업장명": row.get("fact_manage_nm") or row.get("source_candidate_name", ""),
        "원문 주소": row.get("fact_adres", ""),
        "CleanSYS 사업장코드": row.get("source_fact_code") or row.get("fact_code", ""),
        "총배출량 원문값": row.get("dscamt_sm", ""),
        "NOx 배출량 원문값": row.get("nox_dscamt", ""),
        "SOx 배출량 원문값": row.get("sox_dscamt", ""),
        "먼지(TSP) 배출량 원문값": row.get("tsp_dscamt", ""),
        "HCl 배출량 원문값": row.get("hcl_dscamt", ""),
        "HF 배출량 원문값": row.get("hf_dscamt", ""),
        "NH3 배출량 원문값": row.get("nh3_dscamt", ""),
        "CO 배출량 원문값": row.get("co_dscamt", ""),
        "사업자번호": row.get("biz_no", ""),
    }


def _water_common(row):
    return {
        "자료연도": row.get("YEAR") or row.get("year", ""),
        "원문 사업장명": row.get("FACT_FNAME") or row.get("FACT_NAME", ""),
        "원문 주소": row.get("FACT_ADDR", ""),
        "SOOSIRO 사업장코드": row.get("FACT_CODE") or row.get("source_fact_code", ""),
        "방류구번호": row.get("WAST_NO", ""),
    }


def _water_annual(row):
    out = _water_common(row)
    out.update({
        "COD 평균농도 원문값": row.get("COD_AVRG_DNSTY", ""),
        "COD 배출량 원문값": row.get("COD_DSCAMT", ""),
        "TOC 평균농도 원문값": row.get("TOC_AVRG_DNSTY", ""),
        "TOC 배출량 원문값": row.get("TOC_DSCAMT", ""),
        "SS 평균농도 원문값": row.get("SS_AVRG_DNSTY", ""),
        "SS 배출량 원문값": row.get("SS_DSCAMT", ""),
        "T-N 평균농도 원문값": row.get("TN_AVRG_DNSTY", ""),
        "T-N 배출량 원문값": row.get("TN_DSCAMT", ""),
        "T-P 평균농도 원문값": row.get("TP_AVRG_DNSTY", ""),
        "T-P 배출량 원문값": row.get("TP_DSCAMT", ""),
        "BOD 평균농도 원문값": row.get("BOD_AVRG_DNSTY", ""),
        "BOD 배출량 원문값": row.get("BOD_DSCAMT", ""),
        "pH 평균 원문값": row.get("PH_AVRG_DNSTY", ""),
    })
    return out


def _water_daily(row):
    out = _water_annual(row)
    ordered = {
        "자료연도": out.pop("자료연도", ""),
        "일자": row.get("DAY", ""),
        "분기": row.get("QUARTER") or row.get("query_quarter", ""),
        "원문 사업장명": out.pop("원문 사업장명", ""),
        "원문 주소": out.pop("원문 주소", ""),
        "SOOSIRO 사업장코드": out.pop("SOOSIRO 사업장코드", ""),
        "방류구번호": out.pop("방류구번호", ""),
        "유량 원문값": row.get("AMOUNT_FLOW", ""),
    }
    ordered.update(out)
    return ordered


def _review_row(identity):
    return {
        "사업장코드": identity.get("source_site_id", ""),
        "원문 사업장명": identity.get("source_site_name_raw", ""),
        "원문 주소": identity.get("source_address_raw", ""),
        "수집기간": f"{identity.get('valid_from','')} ~ {identity.get('valid_to','')}",
        "검토상태": identity.get("match_status", ""),
        "검토사유": identity.get("match_basis", ""),
        "설명": identity.get("notes", ""),
        "사용원칙": "자료는 보존·열람하되 canonical 사업장에 자동 결합하거나 분석값으로 사용하지 않음",
    }


def _status_sheet(source, status, raw_rows, in_scope_rows, review_rows, years, note=""):
    return [{
        "소스": source,
        "수집상태": status.get("status", "UNKNOWN"),
        "원자료 행수": raw_rows,
        "확정범위 표시행수": in_scope_rows,
        "검토필요 표시행수": review_rows,
        "수집연도": ", ".join(map(str, years)) if years else "",
        "설명": note,
    }]


def build_human_excels(package_root, archive_root, scope):
    package_root = Path(package_root)
    root = package_root / "output"
    user = Path(archive_root) / "01_사용자자료"
    created = []
    fidelity = {"schema_version": "1.0", "sources": {}, "pass": True}

    # CleanSYS
    source = "CLEANSYS_AIR"
    raw = _jsonl(root/source/"annual_rows.jsonl")
    candidates = _json(root/source/"candidates.json", []) or []
    review = _identity_review_map(package_root, source)
    confirmed_ids = set(map(str, scope.get(source, set())))
    review_ids = set(review) - confirmed_ids
    confirmed = [r for r in raw if _source_id(r, source) in confirmed_ids]
    review_rows = [r for r in raw if _source_id(r, source) in review_ids]
    confirmed_candidates = [r for r in candidates if str(r.get("fact_code") or "") in confirmed_ids]
    review_candidates = [r for r in candidates if str(r.get("fact_code") or "") in review_ids]
    status = _status(root, source)
    p = user/"01_TMS"/"대기_CleanSYS"/"CleanSYS_대기TMS_정리.xlsx"
    _write_xlsx(p, [
        ("수집상태", _status_sheet(source,status,len(raw),len(confirmed),len(review_rows),_years([r.get('examin_year') for r in raw]),"배출량 단위는 원문 source 정의를 확인하며 이 파일에서 임의 환산하지 않음")),
        ("확정_연간데이터", [_clean_summary(r) for r in confirmed]),
        ("확정_사업장목록", confirmed_candidates),
        ("검토필요_연간", [_clean_summary(r) for r in review_rows]),
        ("검토필요_사업장", [_review_row(review[i]) for i in sorted(review_ids) if i in review] + review_candidates),
    ])
    created.append(p)
    fidelity["sources"][source] = {"collector_status":status.get("status"),"raw_rows":len(raw),"confirmed_rows":len(confirmed),"review_rows":len(review_rows),"silent_drop":bool(raw and not confirmed and not review_rows)}

    # SOOSIRO
    source = "SOOSIRO_WATER"
    annual = _jsonl(root/source/"annual_rows.jsonl")
    daily = _jsonl(root/source/"daily_rows.jsonl")
    candidates = _json(root/source/"fact_candidates.json", []) or []
    review = _identity_review_map(package_root, source)
    confirmed_ids = set(map(str, scope.get(source, set())))
    review_ids = set(review) - confirmed_ids
    annual_confirmed = [r for r in annual if _source_id(r, source) in confirmed_ids]
    daily_confirmed = [r for r in daily if _source_id(r, source) in confirmed_ids]
    annual_review = [r for r in annual if _source_id(r, source) in review_ids]
    daily_review = [r for r in daily if _source_id(r, source) in review_ids]
    status = _status(root, source)
    p = user/"01_TMS"/"수질_SOOSIRO"/"SOOSIRO_수질TMS_정리.xlsx"
    _write_xlsx(p, [
        ("수집상태", _status_sheet(source,status,len(annual)+len(daily),len(annual_confirmed)+len(daily_confirmed),len(annual_review)+len(daily_review),_years([r.get('YEAR') for r in annual]),"농도·배출량 단위는 원문 source 정의를 확인하며 이 파일에서 임의 환산하지 않음")),
        ("확정_연간데이터", [_water_annual(r) for r in annual_confirmed]),
        ("확정_일자료", [_water_daily(r) for r in daily_confirmed]),
        ("검토필요_연간", [_water_annual(r) for r in annual_review]),
        ("검토필요_일자료", [_water_daily(r) for r in daily_review]),
        ("검토필요_사업장", [_review_row(review[i]) for i in sorted(review_ids) if i in review]),
    ])
    created.append(p)
    fidelity["sources"][source] = {"collector_status":status.get("status"),"raw_rows":len(annual)+len(daily),"confirmed_rows":len(annual_confirmed)+len(daily_confirmed),"review_rows":len(annual_review)+len(daily_review),"silent_drop":bool((annual or daily) and not (annual_confirmed or daily_confirmed) and not (annual_review or daily_review))}

    # PRTR
    source = "PRTR"
    discovery = _csv(root/source/"discovery.csv")
    detail = _jsonl(root/source/"detail_table_rows.jsonl")
    review = _identity_review_map(package_root, source)
    confirmed_ids = set(map(str, scope.get(source, set())))
    review_ids = set(review) - confirmed_ids
    disc_confirmed = [r for r in discovery if _source_id(r, source) in confirmed_ids]
    detail_confirmed = [r for r in detail if _source_id(r, source) in confirmed_ids]
    disc_review = [r for r in discovery if _source_id(r, source) in review_ids]
    detail_review = [r for r in detail if _source_id(r, source) in review_ids]
    status = _status(root, source)
    p = user/"02_화학물질"/"PRTR_배출이동량"/"PRTR_화학물질배출이동량_정리.xlsx"
    _write_xlsx(p, [
        ("수집상태", _status_sheet(source,status,len(discovery),len(disc_confirmed),len(disc_review),_years([r.get('search_year') for r in discovery]),"요약값과 원문 상세표를 분리해 보존함")),
        ("확정_사업장연도", [_prtr_summary(r) for r in disc_confirmed]),
        ("확정_원문표", [_source_table_row(r,'entrps_id') for r in detail_confirmed]),
        ("검토필요_사업장연도", [_prtr_summary(r) for r in disc_review]),
        ("검토필요_원문표", [_source_table_row(r,'entrps_id') for r in detail_review]),
    ])
    created.append(p)
    fidelity["sources"][source] = {"collector_status":status.get("status"),"raw_rows":len(discovery),"confirmed_rows":len(disc_confirmed),"review_rows":len(disc_review),"silent_drop":bool(discovery and not disc_confirmed and not disc_review)}

    # Chemical statistics
    source = "CHEM_STATS"
    discovery = _csv(root/source/"discovery.csv")
    detail = _jsonl(root/source/"detail_table_rows.jsonl")
    review = _identity_review_map(package_root, source)
    confirmed_ids = set(map(str, scope.get(source, set())))
    review_ids = set(review) - confirmed_ids
    disc_confirmed = [r for r in discovery if _source_id(r, source) in confirmed_ids]
    detail_confirmed = [r for r in detail if _source_id(r, source) in confirmed_ids]
    disc_review = [r for r in discovery if _source_id(r, source) in review_ids]
    detail_review = [r for r in detail if _source_id(r, source) in review_ids]
    status = _status(root, source)
    p = user/"02_화학물질"/"화학물질통계"/"화학물질통계_정리.xlsx"
    _write_xlsx(p, [
        ("수집상태", _status_sheet(source,status,len(discovery),len(disc_confirmed),len(disc_review),_years([r.get('search_year') or r.get('reportYear') for r in discovery]),"해당연도 원문 identity와 별도 identity anchor를 구분함")),
        ("확정_사업장연도", [_chem_summary(r) for r in disc_confirmed]),
        ("확정_원문표", [_source_table_row(r,'bplcId') for r in detail_confirmed]),
        ("검토필요_사업장연도", [_chem_summary(r) for r in disc_review]),
        ("검토필요_원문표", [_source_table_row(r,'bplcId') for r in detail_review]),
    ])
    created.append(p)
    fidelity["sources"][source] = {"collector_status":status.get("status"),"raw_rows":len(discovery),"confirmed_rows":len(disc_confirmed),"review_rows":len(disc_review),"silent_drop":bool(discovery and not disc_confirmed and not disc_review)}

    for source, item in fidelity["sources"].items():
        if item["collector_status"] == "DATA_FOUND" and item["raw_rows"] > 0 and item["confirmed_rows"] + item["review_rows"] == 0:
            item["silent_drop"] = True
            fidelity["pass"] = False
    fidelity["principle"] = "DATA_FOUND rows must remain visible either as confirmed requested-scope data or explicitly quarantined REVIEW_REQUIRED data; never silently disappear."
    idx = Path(archive_root)/"00_자료목록"
    idx.mkdir(parents=True, exist_ok=True)
    (idx/"Human_Delivery_Fidelity.json").write_text(json.dumps(fidelity,ensure_ascii=False,indent=2),encoding="utf-8")
    return created
