"""Evidence-first interpretation of five public environmental sources.

Never upgrade company/site identity from similar names, nor treat numeric differences
between distinct public sources as reporting errors. Raw values and source-native
IDs remain unchanged; comparisons live only in a separate human-readable workbook.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup

PUBLIC_URLS = {
    "ENVINFO": "https://www.env-info.kr/",
    "PRTR": "https://icis.mcee.go.kr/prtr/prtrInfo/entrpsSearch.do",
    "CHEM_STATS": "https://icis.mcee.go.kr/",
    "CLEANSYS_AIR": "https://www.cleansys.or.kr/",
    "SOOSIRO_WATER": "https://www.soosiro.or.kr/",
}
VIOLATION_LABEL = "환경법규 위반 내용"
VIOLATION_FIELDS = ("처분기관", "처분일자", "처분내용", "조치내용", "관련 법", "근거법률")
MEASURE_CAPTIONS = {
    "화학물질 배출실적": {"화학물질 배출량": "CHEM_RELEASE"},
    "대기오염물질 배출 실적": {
        "질소산화물": "NOX", "황산화물": "SOX", "먼지": "TSP",
    },
}
CHEMICAL_HEADER = "화학물질 배출량·이동량 정보(kg/년)"


def _csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else default


def _jsonl(path):
    p = Path(path)
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def _decimal(value):
    raw = str(value or "").strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _public_relative(path, root):
    return str(Path(path).relative_to(root).as_posix())


def _site_token(name):
    return set(re.findall(r"[가-힣A-Za-z0-9#]+(?:공장|사업장|터미널)", str(name or "")))


def _simple_table_rows(table):
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        yield (
            re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip(),
            re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True)).strip(),
        )


def parse_envinfo(root):
    """Read caption-bound records only; never keyword-scan unrelated prose.

    Output tracks source-local year/site ID and complete verbatim text for
    actions; no inference that a reported violation equals a court finding.
    """
    env = Path(root) / "ENVINFO"
    discovered = _csv(env / "discovery.csv")
    names = {(str(r.get("year")), str(r.get("compId"))):
             str(r.get("compNm") or "") for r in discovered}
    violations, metrics, qa_issues = [], [], []
    body_paths = sorted((env / "raw_detail").glob("*.html"))
    for path in body_paths:
        file_match = re.match(r"(20\d\d)_(\d+)_", path.name)
        if not file_match:
            qa_issues.append("ENVINFO_UNPARSEABLE_FILENAME:" + path.name)
            continue
        year, site_id = file_match.groups()
        site_name = names.get((year, site_id), "")
        if not site_name:
            qa_issues.append("ENVINFO_DETAIL_NOT_IN_DISCOVERY:" + path.name)
        html_bytes = path.read_bytes()
        soup = BeautifulSoup(html_bytes, "html.parser")
        source_hash = hashlib.sha256(html_bytes).hexdigest()
        provenance = {
            "공개연도": year, "ENVINFO사업장ID": site_id, "사업장원문명": site_name,
            "원문HTML": _public_relative(path, root),
            "공식출처": PUBLIC_URLS["ENVINFO"], "원문SHA256": source_hash,
        }
        legal_tables = 0
        for table in soup.find_all("table"):
            cap = table.find("caption")
            title = re.sub(r"\s+", " ", cap.get_text(" ", strip=True)).strip() if cap else ""
            rows = list(_simple_table_rows(table))
            if "환경관련 법규 위반 현황" in title:
                legal_tables += 1
                current = None
                for label, value in rows:
                    if label == VIOLATION_LABEL:
                        if current is not None:
                            violations.append(current)
                        current = {**provenance, "위반내용_원문": value}
                        for field in VIOLATION_FIELDS:
                            current[field] = ""
                    elif current is not None and label in VIOLATION_FIELDS:
                        current[label] = value
                if current is not None:
                    violations.append(current)
                elif any(label == VIOLATION_LABEL for label, _ in rows):
                    qa_issues.append("LEGAL_VIOLATION_TABLE_UNPARSED:" + path.name)
            for caption_fragment, field_map in MEASURE_CAPTIONS.items():
                if caption_fragment not in title:
                    continue
                for label, content in rows:
                    metric = next(
                        (kind for prefix, kind in field_map.items() if prefix in label), None
                    )
                    if not metric:
                        continue
                    matched = re.match(
                        r"^\s*([0-9][\d,]*(?:\.\d+)?)\s*(ton|kg)\b", content, re.I
                    )
                    if not matched:
                        continue
                    metrics.append({
                        **provenance, "지표": metric, "원문항목": label,
                        "원문수치": matched.group(1), "원문단위": matched.group(2),
                        "원문셀_전체": content,
                        "수치": _decimal(matched.group(1)),
                    })
        if legal_tables == 0:
            qa_issues.append("LEGAL_DISCLOSURE_TABLE_MISSING:" + path.name)
    return violations, metrics, qa_issues


def inspect_identity(root):
    """Source native IDs are parallel records; no crosswalk is certified here."""
    root = Path(root)
    results = []
    env = _csv(root / "ENVINFO" / "discovery.csv")
    for sid, grouped in _group(env, "compId").items():
        results.append({
            "자료원": "ENVINFO", "원본식별자": sid,
            "사업장원문명": " / ".join(sorted({r.get("compNm","") for r in grouped})),
            "원본주소": "", "해당연도": ", ".join(sorted({r.get("year","") for r in grouped})),
            "식별상태": "공식 ENVINFO 등록 ID (타 자료원 ID와 동일성 미확인)",
            "원본근거": "ENVINFO/discovery.csv", "주의": "법인과 공장 공개정보는 별도 행으로 유지",
        })
    prtr = _csv(root / "PRTR" / "discovery.csv")
    for sid, grouped in _group(prtr, "entrps_id").items():
        statuses = sorted({str(r.get("match_status") or "MISSING") for r in grouped})
        results.append({
            "자료원": "PRTR", "원본식별자": sid,
            "사업장원문명": " / ".join(sorted({r.get("company_name_raw","") for r in grouped})),
            "원본주소": " / ".join(sorted({r.get("address_raw","") for r in grouped})),
            "해당연도": ", ".join(sorted({r.get("search_year","") for r in grouped})),
            "식별상태": " / ".join(statuses),
            "원본근거": "PRTR/discovery.csv:match_status",
            "주의": ("UNRESOLVED는 해당 법인·시설 귀속 확정이 아님"
                   if "UNRESOLVED" in statuses else "자료원 간 고유 ID 동일성 확인 필요"),
        })
    chem = _csv(root / "CHEM_STATS" / "discovery.csv")
    for sid, grouped in _group(chem, "bplcId").items():
        results.append({
            "자료원": "CHEM_STATS", "원본식별자": sid,
            "사업장원문명": " / ".join(sorted({r.get("bplcNm","") for r in grouped})),
            "원본주소": " / ".join(sorted({r.get("locplcAdres","") for r in grouped})),
            "해당연도": ", ".join(sorted({r.get("reportYear","") for r in grouped})),
            "식별상태": "공식 조사 사업장 ID (타 자료원 ID와 동일성 미확인)",
            "원본근거": "CHEM_STATS/discovery.csv", "주의": "동일 주소나 법인명만으로 자동 병합 금지",
        })
    for source, filename, id_key, name_key, addr_key in [
        ("CLEANSYS_AIR", "candidates.json", "fact_code", "company_name_raw", ""),
        ("SOOSIRO_WATER", "fact_candidates.json", "FACT_CODE", "FACT_NAME", "FACT_ADDR"),
    ]:
        status = _json(root / source / "status.json", {}) or {}
        rows = _json(root / source / filename, []) or []
        for r in rows:
            results.append({
                "자료원": source, "원본식별자": str(r.get(id_key) or ""),
                "사업장원문명": str(r.get(name_key) or ""),
                "원본주소": str(r.get(addr_key) or ""),
                "해당연도": ", ".join(map(str, status.get("annual_years",[]))),
                "식별상태": "공식 시설코드 후보; 범위 대조 필요",
                "원본근거": source + "/" + filename,
                "주의": (
                    "공개시설 명칭매칭 0건; 별도 경로로 조회" if
                    source == "CLEANSYS_AIR" and status.get("registry_identity_matches") == 0
                    else "조회 성공은 규제 적용성·법인 귀속의 확정과 다름"
                ),
            })
    return results


def _group(rows, key):
    d = defaultdict(list)
    for item in rows:
        sid = str(item.get(key) or "")
        if sid:
            d[sid].append(item)
    return d


def compare_prtr_envinfo(root, metrics):
    """Normalize numeric units only if source-native labels prove both units.

    Comparisons remain provisional when a native site mapping is unresolved.
    A material-difference flag is only a *review hint*, not an accusation.
    """
    root = Path(root)
    prtr = _csv(root / "PRTR" / "discovery.csv")
    detail = _jsonl(root / "PRTR" / "detail_table_rows.jsonl")
    native_unit_proof = {
        (str(r.get("search_year")), str(r.get("entrps_id")))
        for r in detail
        if any(CHEMICAL_HEADER in str(c) for c in r.get("cells", []))
    }
    env_lookup = defaultdict(list)
    for m in metrics:
        if m["지표"] == "CHEM_RELEASE" and m["원문단위"].lower() == "ton":
            env_lookup[m["공개연도"]].append(m)
    results = []
    for r in prtr:
        year, sid = str(r.get("search_year") or ""), str(r.get("entrps_id") or "")
        value = _decimal(r.get("release_total_raw"))
        candidates = env_lookup.get(year, [])
        site_tokens = _site_token(r.get("company_name_raw"))
        by_site = [
            x for x in candidates if site_tokens & _site_token(x["사업장원문명"])
        ]
        row = {
            "연도": year, "PRTR사업장ID": sid,
            "PRTR사업장명": str(r.get("company_name_raw") or ""),
            "PRTR식별상태": str(r.get("match_status") or "MISSING"),
            "PRTR원문배출량": str(r.get("release_total_raw") or ""),
            "PRTR원문단위": "kg/년" if (year, sid) in native_unit_proof else "미확인",
            "ENVINFO사업장ID": "", "ENVINFO원문배출량": "",
            "ENVINFO원문단위": "", "PRTR_환산톤": "", "차이_톤": "",
            "비교판정": "", "집계범위": "미확인 (자료원마다 배출물질·조사범위 차이 가능)",
            "원문근거_PRTR": "PRTR/discovery.csv + PRTR/detail_table_rows.jsonl",
            "원문근거_ENVINFO": "", "처리원칙": "수치차이가 있더라도 오류 단정 금지",
        }
        if len(by_site) != 1:
            row["비교판정"] = "SITE_PAIRING_AMBIGUOUS_OR_MISSING"
        elif (year, sid) not in native_unit_proof or value is None:
            row["비교판정"] = "PRTR_UNIT_OR_NUMBER_NOT_SOURCE_VERIFIED"
        else:
            matched = by_site[0]
            row["ENVINFO사업장ID"] = matched["ENVINFO사업장ID"]
            row["ENVINFO원문배출량"] = matched["원문수치"]
            row["ENVINFO원문단위"] = matched["원문단위"]
            row["원문근거_ENVINFO"] = matched["원문HTML"]
            in_ton = value / Decimal(1000)
            difference = matched["수치"] - in_ton
            row["PRTR_환산톤"] = float(in_ton)
            row["차이_톤"] = float(difference)
            # Both materiality cutoffs are *screening heuristics* only;
            # not a legal tolerance or permitted measurement error.
            threshold = abs(difference) > Decimal(1) and (
                abs(difference) / max(abs(matched["수치"]), Decimal("0.00001"))
            ) > Decimal("0.01")
            row["비교판정"] = ("MATERIAL_DIFFERENCE_REVIEW" if threshold else
                          "NUMERIC_COMPARISON_ONLY_SCOPE_UNCONFIRMED")
        if row["PRTR식별상태"] != "MATCHED":
            row["처리원칙"] += "; PRTR 식별 미확정"
        results.append(row)
    return results


def compare_air_envinfo(root, metrics):
    """No kg→ton conversion absent independent captured source unit evidence."""
    root = Path(root)
    clean = _jsonl(root / "CLEANSYS_AIR" / "annual_rows.jsonl")
    status = _json(root / "CLEANSYS_AIR" / "status.json", {}) or {}
    env_by_year = defaultdict(list)
    for m in metrics:
        if m["지표"] == "NOX":
            env_by_year[m["공개연도"]].append(m)
    rows = []
    for r in clean:
        year = str(r.get("examin_year") or "")
        by_site = [
            m for m in env_by_year.get(year, [])
            if _site_token(r.get("fact_manage_nm")) & _site_token(m["사업장원문명"])
        ]
        found = by_site[0] if len(by_site) == 1 else None
        rows.append({
            "연도": year, "CleanSYS시설ID": str(r.get("fact_code") or ""),
            "CleanSYS원문시설명": str(r.get("fact_manage_nm") or ""),
            "CleanSYS_NOx원문수치": r.get("nox_dscamt"),
            "CleanSYS원문단위": "단위 증빙 없음 (원본 필드명만 확보)",
            "ENVINFO사업장ID": found["ENVINFO사업장ID"] if found else "",
            "ENVINFO_NOx원문수치": found["원문수치"] if found else "",
            "ENVINFO단위": found["원문단위"] if found else "",
            "CleanSYS_단위검증": "NOT_VERIFIED_IN_CAPTURE",
            "집계범위": "NOT_VERIFIED_AS_EQUIVALENT",
            "비교판정": "NO_AUTOMATIC_NUMERIC_DIFF_UNVERIFIED_UNIT_AND_SCOPE",
            "공개시설명_직접매칭건수": status.get("registry_identity_matches"),
            "통신TLS인증": status.get("tls_verification"),
            "원문근거": "CLEANSYS_AIR/annual_rows.jsonl; " +
                      (found["원문HTML"] if found else "ENVINFO site missing"),
            "주의": "조회 성공 및 명칭 유사성은 집계범위 동일성·규제 적용성의 증거가 아님",
        })
    return rows


def review(root):
    violations, metrics, qa = parse_envinfo(root)
    identities = inspect_identity(root)
    prtr = compare_prtr_envinfo(root, metrics)
    air = compare_air_envinfo(root, metrics)
    flags = sorted(set(
        ["PRTR_SITE_IDENTITY_UNRESOLVED" for r in identities
         if r["자료원"] == "PRTR" and "UNRESOLVED" in r["식별상태"]]
        + ["PRTR_ENVINFO_MATERIAL_DIFFERENCE_REVIEW" for r in prtr
           if r["비교판정"] == "MATERIAL_DIFFERENCE_REVIEW"]
        + ["CLEANSYS_SOURCE_UNIT_AND_SCOPE_NOT_VERIFIED" for r in air
           if r["비교판정"].startswith("NO_AUTOMATIC_NUMERIC")]
    ))
    overview = [
        {"항목": "ENVINFO 행정처분 원문 추출",
         "결과": f"{len(violations)}개 공개기록", "판정": "원문 전사, 법적 확정판단 아님",
         "확인방법": "공개연도·원문사업장ID·원문HTML·처분일자 모두 제공"},
        {"항목": "자료원별 사업장 식별",
         "결과": f"{len(identities)}개 출처별 식별자", "판정": "상호 동일성 미확인",
         "확인방법": "PRTR match_status 등 공식 수집상태 그대로 유지"},
        {"항목": "PRTR ↔ ENVINFO 화학물질 배출량",
         "결과": f"{len(prtr)}개 연도별 조회", "판정": "집계범위 차이/정정 가능성 검토",
         "확인방법": "PRTR 원문 kg/년 헤더가 존재할 때만 톤 환산"},
        {"항목": "CleanSYS ↔ ENVINFO NOx",
         "결과": f"{len(air)}개 연도별 조회", "판정": "단위 및 집계범위 검증 전 수치차이 계산 금지",
         "확인방법": "원본 필드명·원문량 보존, 단위 미증빙 표시"},
        {"항목": "검토 대상",
         "결과": "; ".join(flags) or "없음", "판정": "미해결이면 최종 직무분석 확정본 아님",
         "확인방법": "공식 원문 대조 및 사업장 귀속 재확인 필요"},
    ]
    # Decimal values are only used internally; raw values are preserved in XLSX.
    source_metrics = [
        {k: float(v) if isinstance(v, Decimal) else v for k, v in m.items()}
        for m in metrics
    ]
    return {
        "status": "INTERPRETATION_REVIEW_REQUIRED" if (flags or qa) else "STRUCTURED_EXTRACTION_COMPLETE",
        "flags": flags, "qa_issues": qa, "overview": overview,
        "identity_rows": identities, "violation_rows": violations,
        "prtr_comparison_rows": prtr, "air_comparison_rows": air,
        "envinfo_metric_rows": source_metrics,
    }
