"""Separate BAT technical relevance from legal applicability and company adoption.

The BAT resolver intentionally matches industry/process/utility evidence.  That is a
technical-reference decision, not proof that the selected site is legally subject to
the Integrated Environmental Management regime, and not proof that the company has
adopted a BAT technique.  This module makes those three claims explicit and fail-closed.

Legal target/non-target states are promoted only from explicit evidence.  Absence from
an IEPS/public record is never treated as NON_TARGET.  Positive IEPS evidence may prove
TARGET_CONFIRMED; NON_TARGET_CONFIRMED requires an explicit applicability contract or
an equivalent future official adapter.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

LEGAL_TARGET = "TARGET_CONFIRMED"
LEGAL_NON_TARGET = "NON_TARGET_CONFIRMED"
LEGAL_UNKNOWN = "UNKNOWN"
LEGAL_STATES = {LEGAL_TARGET, LEGAL_NON_TARGET, LEGAL_UNKNOWN}

EXTRA_FIELDS = [
    "site_legal_applicability_state",
    "site_legal_applicability_source",
    "technical_relevance_state",
    "company_adoption_state",
    "bat_reference_use",
    "interpretation_boundary",
]

IEPS_HOST = "ieps.nier.go.kr"
IEPS_MARKERS = (
    "통합환경허가",
    "통합관리사업장",
    "환경오염시설의 통합관리에 관한 법률",
    "환경오염시설법",
)
STRONG_VERIFICATION = {"VERIFIED", "SOURCE_VERIFIED"}


def _read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return [], []
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path, rows, fields):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _host(value):
    try:
        return (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _norm(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _valid_source(value):
    return _host(value) != ""


def _explicit_contract_entries(package):
    package = Path(package)
    paths = [
        package / "Integrated_Environmental_Management_Applicability.json",
        package / "output" / "IEPS" / "applicability.json",
    ]
    out = []
    for path in paths:
        payload = _read_json(path, {}) or {}
        items = payload.get("sites") or payload.get("entries") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            state = str(item.get("legal_applicability_state") or item.get("state") or "").upper()
            cid = str(item.get("canonical_site_id") or "").strip()
            source = str(item.get("source_locator") or item.get("source_url") or "").strip()
            if cid and state in {LEGAL_TARGET, LEGAL_NON_TARGET} and _valid_source(source):
                out.append({
                    "canonical_site_id": cid,
                    "state": state,
                    "source_locator": source,
                    "evidence_type": str(item.get("evidence_type") or "EXPLICIT_APPLICABILITY_CONTRACT"),
                })
    return out


def _positive_ieps_entries(package, candidate_rows):
    """Infer only positive TARGET evidence from downloaded, strongly verified IEPS docs."""
    package = Path(package)
    docs, _ = _read_csv(package / "output" / "CORP_DOCS" / "document_index.csv")
    site_names = {
        str(r.get("canonical_site_id") or ""): str(r.get("site_name") or "")
        for r in candidate_rows
        if str(r.get("canonical_site_id") or "")
    }
    out = []
    for row in docs:
        verification = str(row.get("verification_status") or "").upper()
        status = str(row.get("collection_status") or "").upper()
        locator = str(row.get("source_locator") or row.get("source_url") or "")
        if verification not in STRONG_VERIFICATION or status != "DOWNLOADED":
            continue
        if _host(locator) != IEPS_HOST:
            continue
        text = " ".join(str(row.get(k) or "") for k in ("title", "notes", "original_filename", "source_locator"))
        if not any(marker in text for marker in IEPS_MARKERS):
            continue
        cid = str(row.get("canonical_site_id") or "").strip()
        if not cid:
            raw_site = _norm(row.get("site_name_raw"))
            matches = [key for key, name in site_names.items() if raw_site and raw_site == _norm(name)]
            if len(matches) == 1:
                cid = matches[0]
        if not cid:
            continue
        out.append({
            "canonical_site_id": cid,
            "state": LEGAL_TARGET,
            "source_locator": locator,
            "evidence_type": "IEPS_DOWNLOADED_OFFICIAL_DOCUMENT",
        })
    return out


def _legal_map(package, candidate_rows):
    evidence = [*_explicit_contract_entries(package), *_positive_ieps_entries(package, candidate_rows)]
    by_site = {}
    conflicts = []
    for item in evidence:
        cid = item["canonical_site_id"]
        previous = by_site.get(cid)
        if previous and previous["state"] != item["state"]:
            conflicts.append({"canonical_site_id": cid, "evidence": [previous, item]})
            by_site[cid] = {
                "state": LEGAL_UNKNOWN,
                "source_locator": "",
                "evidence_type": "CONFLICTING_EXPLICIT_EVIDENCE",
            }
        elif not previous:
            by_site[cid] = item
    return by_site, evidence, conflicts


def _technical_state(row):
    state = str(row.get("applicability_state") or "").upper()
    if state == "STRONG_CANDIDATE":
        return "STRONG"
    if state == "SUPPORTING_CANDIDATE":
        return "SUPPORTING"
    if state == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    return "UNRESOLVED"


def _reference_use(legal_state, technical_state):
    if legal_state == LEGAL_TARGET:
        return "LEGAL_AND_TECHNICAL_CONTEXT"
    if legal_state == LEGAL_NON_TARGET:
        return "TECHNICAL_REFERENCE_ONLY"
    if technical_state in {"STRONG", "SUPPORTING", "REVIEW_REQUIRED"}:
        return "TECHNICAL_REFERENCE_PENDING_LEGAL_SCOPE"
    return "REFERENCE_ONLY_UNRESOLVED"


def annotate(package, plan):
    """Annotate BAT candidates without changing the technical collection decision."""
    package = Path(package)
    rows = [dict(r) for r in (plan.get("candidates") or [])]
    legal_by_site, evidence, conflicts = _legal_map(package, rows)

    for row in rows:
        cid = str(row.get("canonical_site_id") or "")
        legal = legal_by_site.get(cid) or {
            "state": LEGAL_UNKNOWN,
            "source_locator": "",
            "evidence_type": "NO_EXPLICIT_LEGAL_APPLICABILITY_EVIDENCE",
        }
        technical = _technical_state(row)
        row["site_legal_applicability_state"] = legal["state"]
        row["site_legal_applicability_source"] = legal.get("source_locator") or ""
        row["technical_relevance_state"] = technical
        row["company_adoption_state"] = "NOT_VERIFIED"
        row["bat_reference_use"] = _reference_use(legal["state"], technical)
        row["interpretation_boundary"] = (
            "Technical BAT matching is separate from Integrated Environmental Management legal applicability. "
            "Downloaded BAT material does not prove company adoption."
        )

    scoped = dict(plan)
    scoped["schema_version"] = "1.4"
    scoped["candidates"] = rows
    boundaries = list(scoped.get("boundaries") or [])
    for note in (
        "BAT technical relevance is not legal applicability under the Integrated Environmental Management regime.",
        "NON_TARGET is never inferred from absence; only explicit official evidence may establish TARGET/NON_TARGET.",
        "BAT reference collection never proves company adoption of the technique.",
    ):
        if note not in boundaries:
            boundaries.append(note)
    scoped["boundaries"] = boundaries

    csv_path = package / "BAT_Applicability_Candidates.csv"
    _, existing_fields = _read_csv(csv_path)
    fields = list(existing_fields)
    if not fields and rows:
        fields = list(rows[0])
    for field in EXTRA_FIELDS:
        if field not in fields:
            fields.append(field)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    _write_csv(csv_path, rows, fields)
    (package / "BAT_Collection_Plan.json").write_text(
        json.dumps(scoped, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    site_states = {}
    for row in rows:
        cid = str(row.get("canonical_site_id") or "")
        if cid:
            site_states[cid] = row.get("site_legal_applicability_state") or LEGAL_UNKNOWN
    counts = Counter(site_states.values())
    boundary = {
        "schema_version": "1.0",
        "site_legal_applicability_counts": dict(counts),
        "site_states": [
            {
                "canonical_site_id": cid,
                "legal_applicability_state": state,
                "source_locator": (legal_by_site.get(cid) or {}).get("source_locator", ""),
            }
            for cid, state in sorted(site_states.items())
        ],
        "explicit_evidence": evidence,
        "conflicts": conflicts,
        "company_adoption_default": "NOT_VERIFIED",
        "principle": (
            "Legal applicability, technical relevance and company adoption are separate claims. "
            "No BAT file or technical match alone establishes legal applicability or adoption."
        ),
    }
    boundary_path = package / "BAT_Legal_Technical_Boundary.json"
    boundary_path.write_text(json.dumps(boundary, ensure_ascii=False, indent=2), encoding="utf-8")
    return scoped, boundary
