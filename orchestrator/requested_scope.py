"""Requested-scope resolver for human delivery and downstream analysis.

Collectors deliberately preserve legal-entity-wide raw evidence.  This module never
truncates collector output.  It only resolves the user-requested company/site scope
for delivery and analysis, using verified Discovery site candidates plus integrated
Site_Master/Source_Identity evidence.
"""

import csv
import json
import re
from pathlib import Path

CORE_SOURCES = ("ENVINFO", "PRTR", "CHEM_STATS", "CLEANSYS_AIR", "SOOSIRO_WATER")


def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def read_csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _plain(value):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def normalize_address(value):
    text = str(value or "")
    replacements = {
        "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
        "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
        "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기",
        "충청남도": "충남", "충청북도": "충북", "전라남도": "전남",
        "전라북도": "전북", "경상남도": "경남", "경상북도": "경북",
        "강원특별자치도": "강원", "강원도": "강원", "제주특별자치도": "제주",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return _plain(text)


def company_terms(profile):
    values = [profile.get("company_display_name"), profile.get("requested_company_name")]
    for alias in profile.get("aliases", []) or []:
        if isinstance(alias, dict):
            values.append(alias.get("term") or alias.get("name"))
        else:
            values.append(alias)
    out = []
    for value in values:
        token = _plain(value)
        for suffix in ("주식회사", "유한회사", "㈜", "주"):
            token = token.replace(_plain(suffix), "")
        if token and token not in out:
            out.append(token)
    return sorted(out, key=len, reverse=True)


def normalize_site_name(value, profile):
    token = _plain(value)
    for company in company_terms(profile):
        token = token.replace(company, "")
    for suffix in ("주식회사", "유한회사", "사업장", "공장", "캠퍼스", "연구원", "사업소", "본사"):
        token = token.replace(_plain(suffix), "")
    return token


def _address_match(left, right):
    a = normalize_address(left)
    b = normalize_address(right)
    if not a or not b:
        return False
    return a == b or (len(a) >= 12 and a in b) or (len(b) >= 12 and b in a)


def _site_name_match(left, right, profile):
    a = normalize_site_name(left, profile)
    b = normalize_site_name(right, profile)
    # Empty normalized names are never evidence of a match.  This explicitly fixes
    # generic rows such as "삼성전자(주)" matching every DS site.
    if not a or not b:
        return False
    return a == b or (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a)


def selected_candidates(profile):
    candidates = [x for x in (profile.get("site_candidates", []) or []) if isinstance(x, dict)]
    scope = profile.get("requested_scope") or {"mode": "COMPANY"}
    mode = str(scope.get("mode") or "COMPANY").upper()
    if mode != "SITE_SET":
        return candidates, mode
    wanted = {str(x) for x in scope.get("candidate_ids", []) or []}
    selected = [x for x in candidates if str(x.get("candidate_id") or "") in wanted]
    return selected, mode


def resolve_requested_scope(package_root, profile=None):
    root = Path(package_root)
    profile = profile or (read_json(root / "Company_Profile.json", {}) or {})
    candidates, mode = selected_candidates(profile)
    sites = read_csv(root / "Site_Master.csv")
    identities = read_csv(root / "Source_Identity.csv")

    if mode != "SITE_SET":
        canonical = {r.get("canonical_site_id", "") for r in sites if r.get("identity_status") == "CONFIRMED" and r.get("canonical_site_id")}
        source_ids = {s: set() for s in CORE_SOURCES}
        labels = {}
        for row in identities:
            source = row.get("source_key", "")
            sid = str(row.get("source_site_id") or "")
            if source in source_ids and sid:
                source_ids[source].add(sid)
                labels[(source, sid)] = row.get("source_site_name_raw", "")
        return {
            "mode": mode, "label": (profile.get("requested_scope") or {}).get("label", "COMPANY"),
            "target_candidate_ids": [x.get("candidate_id", "") for x in candidates],
            "target_canonical_site_ids": canonical, "target_source_ids": source_ids,
            "source_labels": labels, "unresolved_candidates": [],
        }

    canonical = set()
    unresolved = []
    for candidate in candidates:
        matching = []
        for site in sites:
            if site.get("identity_status") != "CONFIRMED":
                continue
            if _address_match(candidate.get("address_raw"), site.get("canonical_address_key")) or _site_name_match(candidate.get("site_name_raw"), site.get("canonical_site_name"), profile):
                matching.append(site.get("canonical_site_id", ""))
        matching = [x for x in dict.fromkeys(matching) if x]
        if matching:
            canonical.update(matching)
        else:
            unresolved.append({
                "candidate_id": candidate.get("candidate_id", ""),
                "site_name_raw": candidate.get("site_name_raw", ""),
                "address_raw": candidate.get("address_raw", ""),
                "reason": "NO_CONFIRMED_CANONICAL_SITE_MATCH",
            })

    source_ids = {s: set() for s in CORE_SOURCES}
    labels = {}
    for row in identities:
        source = row.get("source_key", "")
        sid = str(row.get("source_site_id") or "")
        if source not in source_ids or not sid:
            continue
        include = row.get("canonical_site_id") in canonical
        if not include:
            include = any(
                _address_match(c.get("address_raw"), row.get("source_address_raw")) or
                _site_name_match(c.get("site_name_raw"), row.get("source_site_name_raw"), profile)
                for c in candidates
            )
        if include:
            source_ids[source].add(sid)
            labels[(source, sid)] = row.get("source_site_name_raw", "")

    return {
        "mode": mode, "label": (profile.get("requested_scope") or {}).get("label", "SITE_SET"),
        "target_candidate_ids": [x.get("candidate_id", "") for x in candidates],
        "target_canonical_site_ids": canonical, "target_source_ids": source_ids,
        "source_labels": labels, "unresolved_candidates": unresolved,
    }


def source_id_scope(package_root, profile):
    """Adapter matching archive_builder.source_id_scope return contract."""
    resolved = resolve_requested_scope(package_root, profile)
    tokens = [(c.get("site_name_raw", ""), normalize_site_name(c.get("site_name_raw", ""), profile)) for c in selected_candidates(profile)[0]]
    return resolved["target_source_ids"], resolved["source_labels"], tokens


def _serialize_scope(scope):
    return {
        "schema_version": "1.0",
        "mode": scope["mode"],
        "label": scope["label"],
        "target_candidate_ids": scope["target_candidate_ids"],
        "target_canonical_site_ids": sorted(scope["target_canonical_site_ids"]),
        "target_source_ids": {k: sorted(v) for k, v in scope["target_source_ids"].items()},
        "unresolved_candidates": scope["unresolved_candidates"],
        "principle": "Raw collector artifacts remain company-wide; only delivery/analysis views are narrowed to requested scope.",
    }


def apply_requested_scope(package_root):
    """Filter only the analysis view and inherit company-scope event links.

    Raw source files, Source_Identity, Site_Master and Event_Registry are never
    truncated.  Analysis rows are kept when their canonical site is targeted or when
    the source-native ID is a targeted-but-still-review-required site.
    """
    root = Path(package_root)
    profile = read_json(root / "Company_Profile.json", {}) or {}
    scope = resolve_requested_scope(root, profile)
    serialized = _serialize_scope(scope)
    (root / "Requested_Scope.json").write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")

    scope_rows = []
    for source in CORE_SOURCES:
        for sid in sorted(scope["target_source_ids"].get(source, set())):
            scope_rows.append({
                "scope_label": scope["label"], "source_key": source, "source_site_id": sid,
                "source_site_name_raw": scope["source_labels"].get((source, sid), ""),
            })
    write_csv(root / "Analysis_Scope.csv", scope_rows, ["scope_label", "source_key", "source_site_id", "source_site_name_raw"])

    path = root / "Analysis_Ready_Index.csv"
    rows = read_csv(path)
    if not rows:
        return {**serialized, "analysis_rows_before": 0, "analysis_rows_after": 0}

    company_links = {}
    site_links = {}
    for link in read_csv(root / "Coverage_Event_Links.csv"):
        key = (link.get("source_key", ""), link.get("canonical_site_id", ""))
        target = company_links if not link.get("canonical_site_id") else site_links
        target.setdefault(key, []).append(link.get("link_id", ""))

    kept = []
    for row in rows:
        source = row.get("source_key", "")
        sid = str(row.get("source_site_id") or "")
        canonical = row.get("canonical_site_id", "")
        if scope["mode"] == "SITE_SET" and canonical not in scope["target_canonical_site_ids"] and sid not in scope["target_source_ids"].get(source, set()):
            continue
        inherited = []
        inherited.extend(company_links.get((source, ""), []))
        if canonical:
            inherited.extend(site_links.get((source, canonical), []))
        existing = [x for x in str(row.get("event_link_ids") or "").split("|") if x]
        merged = list(dict.fromkeys(existing + [x for x in inherited if x]))
        row["event_link_ids"] = "|".join(merged)
        kept.append(row)

    fields = list(rows[0].keys())
    write_csv(path, kept, fields)
    return {**serialized, "analysis_rows_before": len(rows), "analysis_rows_after": len(kept)}
