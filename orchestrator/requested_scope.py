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


def _entity_plain(value):
    text = str(value or "")
    text = re.sub(r"\(\s*주\s*\)|㈜|주식회사|유한회사|\(\s*유\s*\)", "", text, flags=re.I)
    return _plain(text)


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
    # Some public registers insert a legal-dong before the road name while the
    # first-party road address omits it (e.g. "성암동 처용로", "평여동 여수산단3로").
    # Remove only a 동/가 token immediately before a road name. 읍/면 remain because
    # they are part of the road-address hierarchy.
    text = re.sub(
        r"\s+[0-9A-Za-z가-힣]+(?:동|가)\s+(?=[0-9A-Za-z가-힣·._-]+(?:로|길)\s*\d)",
        " ",
        text,
    )
    m = re.match(r"^(.*?(?:로|길)\s*\d+(?:-\d+)?)\b", text)
    if m:
        text = m.group(1)
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


def _company_entity_terms(profile):
    values = [profile.get("company_display_name"), profile.get("requested_company_name")]
    for alias in profile.get("aliases", []) or []:
        if isinstance(alias, dict):
            if alias.get("scope") in {"historical", "predecessor"}:
                continue
            if alias.get("search_enabled") is False:
                continue
            values.append(alias.get("term") or alias.get("name"))
        else:
            values.append(alias)
    out = []
    for value in values:
        token = _entity_plain(value)
        if len(token) >= 2 and token not in out:
            out.append(token)
    return sorted(out, key=len, reverse=True)


def normalize_site_name(value, profile):
    token = _plain(value)
    for company in company_terms(profile):
        token = token.replace(company, "")
    for suffix in ("주식회사", "유한회사", "사업장", "공장", "캠퍼스", "연구원", "사업소", "본사"):
        token = token.replace(_plain(suffix), "")
    return token


def _site_core(value, profile):
    token = normalize_site_name(value, profile)
    for suffix in ("제철소", "사업부", "제조소", "센터", "plant", "works"):
        s = _plain(suffix)
        if s and token.endswith(s):
            token = token[:-len(s)]
    return token


def _core_match(left, right):
    a = str(left or "")
    b = str(right or "")
    if not a or not b:
        return False
    return a == b or (len(a) >= 2 and len(b) >= 2 and (a.startswith(b) or b.startswith(a)))


def _source_entity_compatible(value, profile, candidates):
    """Fail closed when a source-native name looks like another legal entity.

    Broad company-name queries intentionally preserve candidates such as subsidiaries.
    Address equality is therefore not sufficient to put a source ID into a requested
    site set. Accept an ID only when its source-native name identifies the current
    company or one of the requested site labels.
    """
    raw = _entity_plain(value)
    if not raw:
        return False, "SOURCE_ENTITY_NAME_MISSING"

    site_cores = [
        _site_core(c.get("site_name_raw"), profile)
        for c in candidates
        if isinstance(c, dict) and _site_core(c.get("site_name_raw"), profile)
    ]

    for excluded in profile.get("related_entity_exclusions", []) or []:
        ex = _entity_plain(excluded)
        if ex and raw.startswith(ex):
            return False, "VERIFIED_RELATED_ENTITY_EXCLUSION"

    terms = _company_entity_terms(profile)
    if raw in terms:
        return True, "CURRENT_COMPANY_EXACT"

    normalized_site = _site_core(value, profile)
    if any(_core_match(normalized_site, site) for site in site_cores):
        return True, "REQUESTED_SITE_NAME"

    for term in terms:
        if not raw.startswith(term):
            continue
        remainder = raw[len(term):]
        if not remainder:
            return True, "CURRENT_COMPANY_EXACT"
        remainder_core = _site_core(remainder, {})
        if any(_core_match(remainder_core, site) for site in site_cores):
            return True, "CURRENT_COMPANY_REQUESTED_SITE"
        if any(remainder.startswith(_entity_plain(x)) for x in ("본사", "사업장", "공장", "캠퍼스", "연구원", "사업소", "제철소")):
            return True, "CURRENT_COMPANY_FACILITY_LABEL"
        # A longer corporate-looking name after the current-company token is not
        # evidence of current-company identity (e.g. COMPANY + FUTUREM/CHEMICAL).
        return False, "SOURCE_ENTITY_NAME_EXTENDS_CURRENT_COMPANY"

    return False, "SOURCE_ENTITY_NAME_NOT_CURRENT_COMPANY"


def _current_entity_active_period(profile):
    explicit = profile.get("current_legal_name_active_period")
    if isinstance(explicit, dict) and (explicit.get("start_year") is not None or explicit.get("end_year") is not None):
        return {"start_year": explicit.get("start_year"), "end_year": explicit.get("end_year")}

    for alias in profile.get("aliases", []) or []:
        if not isinstance(alias, dict) or alias.get("alias_type") != "current_legal_name":
            continue
        start = alias.get("year_start")
        end = alias.get("year_end")
        start = None if start in (None, "", 0, "0") else int(start)
        end = None if end in (None, "", "auto", 0, "0") else int(end)
        if start is not None or end is not None:
            return {"start_year": start, "end_year": end}
    return {}


def _year(value):
    m = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def _time_in_current_entity_period(value, period):
    if not period:
        return True
    y = _year(value)
    if y is None:
        return True
    start = period.get("start_year")
    end = period.get("end_year")
    if start is not None and y < int(start):
        return False
    if end is not None and y > int(end):
        return False
    return True


def _address_match(left, right):
    a = normalize_address(left)
    b = normalize_address(right)
    if not a or not b:
        return False
    return a == b or (len(a) >= 12 and a in b) or (len(b) >= 12 and b in a)


def _site_name_match(left, right, profile):
    a = normalize_site_name(left, profile)
    b = normalize_site_name(right, profile)
    # Empty normalized names are never evidence of a match. This explicitly fixes
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


def _selected_address_counts(candidates):
    counts = {}
    for candidate in candidates:
        key = normalize_address(candidate.get("address_raw"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _candidate_matches(candidate, site_name, site_address, profile, address_counts):
    addr_match = _address_match(candidate.get("address_raw"), site_address)
    name_match = _site_name_match(candidate.get("site_name_raw"), site_name, profile)
    key = normalize_address(candidate.get("address_raw"))
    # If the company's official list has multiple units at one address, address alone
    # cannot decide which organizational unit a public environmental facility belongs
    # to. Require both address and unit-name evidence and keep unmatched colocated units
    # explicitly unresolved rather than silently merging them.
    if key and address_counts.get(key, 0) > 1:
        return addr_match and name_match
    return addr_match or name_match


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
            "source_labels": labels, "unresolved_candidates": [], "excluded_source_ids": [],
            "current_legal_entity_active_period": _current_entity_active_period(profile),
        }

    address_counts = _selected_address_counts(candidates)
    canonical = set()
    unresolved = []
    for candidate in candidates:
        matching = []
        for site in sites:
            if site.get("identity_status") != "CONFIRMED":
                continue
            entity_ok, _ = _source_entity_compatible(site.get("canonical_site_name"), profile, candidates)
            if not entity_ok:
                continue
            if _candidate_matches(candidate, site.get("canonical_site_name"), site.get("canonical_address_key"), profile, address_counts):
                matching.append(site.get("canonical_site_id", ""))
        matching = [x for x in dict.fromkeys(matching) if x]
        if matching:
            canonical.update(matching)
        else:
            key = normalize_address(candidate.get("address_raw"))
            reason = "COLOCATED_OFFICIAL_UNIT_NOT_DISTINCTLY_CONFIRMED" if key and address_counts.get(key, 0) > 1 else "NO_CONFIRMED_CANONICAL_SITE_MATCH"
            unresolved.append({
                "candidate_id": candidate.get("candidate_id", ""),
                "site_name_raw": candidate.get("site_name_raw", ""),
                "address_raw": candidate.get("address_raw", ""),
                "reason": reason,
            })

    source_ids = {s: set() for s in CORE_SOURCES}
    labels = {}
    excluded_source_ids = []
    for row in identities:
        source = row.get("source_key", "")
        sid = str(row.get("source_site_id") or "")
        if source not in source_ids or not sid:
            continue

        entity_ok, entity_reason = _source_entity_compatible(row.get("source_site_name_raw"), profile, candidates)
        if not entity_ok:
            excluded_source_ids.append({
                "source_key": source,
                "source_site_id": sid,
                "source_site_name_raw": row.get("source_site_name_raw", ""),
                "reason": entity_reason,
            })
            continue

        include = row.get("canonical_site_id") in canonical
        if not include:
            include = any(
                _candidate_matches(c, row.get("source_site_name_raw"), row.get("source_address_raw"), profile, address_counts)
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
        "excluded_source_ids": excluded_source_ids,
        "current_legal_entity_active_period": _current_entity_active_period(profile),
    }


def source_id_scope(package_root, profile):
    """Adapter matching archive_builder.source_id_scope return contract."""
    resolved = resolve_requested_scope(package_root, profile)
    tokens = [(c.get("site_name_raw", ""), normalize_site_name(c.get("site_name_raw", ""), profile)) for c in selected_candidates(profile)[0]]
    return resolved["target_source_ids"], resolved["source_labels"], tokens


def _serialize_scope(scope):
    return {
        "schema_version": "1.1",
        "mode": scope["mode"],
        "label": scope["label"],
        "target_candidate_ids": scope["target_candidate_ids"],
        "target_canonical_site_ids": sorted(scope["target_canonical_site_ids"]),
        "target_source_ids": {k: sorted(v) for k, v in scope["target_source_ids"].items()},
        "unresolved_candidates": scope["unresolved_candidates"],
        "excluded_source_ids": scope.get("excluded_source_ids", []),
        "current_legal_entity_active_period": scope.get("current_legal_entity_active_period", {}),
        "principle": "Raw collector artifacts remain company-wide; only delivery/analysis views are narrowed to requested scope. Current-company analysis also respects the verified legal-entity active period.",
    }


def apply_requested_scope(package_root):
    """Filter only the analysis view and inherit company-scope event links.

    Raw source files, Source_Identity, Site_Master and Event_Registry are never
    truncated. Analysis rows are kept when their canonical site is targeted or when
    the source-native ID is a targeted-but-still-review-required site. Rows outside
    the current legal entity's verified active period are retained for traceability
    but made ineligible for current-company analysis.
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
        return {**serialized, "analysis_rows_before": 0, "analysis_rows_after": 0, "temporal_rows_held": 0}

    company_links = {}
    site_links = {}
    for link in read_csv(root / "Coverage_Event_Links.csv"):
        key = (link.get("source_key", ""), link.get("canonical_site_id", ""))
        target = company_links if not link.get("canonical_site_id") else site_links
        target.setdefault(key, []).append(link.get("link_id", ""))

    kept = []
    temporal_rows_held = 0
    period = scope.get("current_legal_entity_active_period") or {}
    for row in rows:
        source = row.get("source_key", "")
        sid = str(row.get("source_site_id") or "")
        canonical_id = row.get("canonical_site_id", "")
        if scope["mode"] == "SITE_SET" and canonical_id not in scope["target_canonical_site_ids"] and sid not in scope["target_source_ids"].get(source, set()):
            continue

        if not _time_in_current_entity_period(row.get("time_key"), period):
            temporal_rows_held += 1
            row["analysis_readiness"] = "TEMPORAL_ENTITY_REVIEW"
            row["analysis_eligible"] = False
            note = "Outside current legal entity active period; raw source evidence retained but excluded from current-company analysis."
            row["notes"] = (str(row.get("notes") or "").strip() + " " + note).strip()

        inherited = []
        inherited.extend(company_links.get((source, ""), []))
        if canonical_id:
            inherited.extend(site_links.get((source, canonical_id), []))
        existing = [x for x in str(row.get("event_link_ids") or "").split("|") if x]
        merged = list(dict.fromkeys(existing + [x for x in inherited if x]))
        row["event_link_ids"] = "|".join(merged)
        kept.append(row)

    fields = list(rows[0].keys())
    write_csv(path, kept, fields)
    return {
        **serialized,
        "analysis_rows_before": len(rows),
        "analysis_rows_after": len(kept),
        "temporal_rows_held": temporal_rows_held,
    }
