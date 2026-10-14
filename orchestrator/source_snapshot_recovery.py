"""Fail-closed recovery of a verified original PRTR snapshot after host outage.

Only a previously accepted, same-company, same-year, source-native PRTR artifact
can be reused. Recovery is NOT a fresh collection. It is recorded separately
and explicitly disclosed in the first sheet of the user's Excel export.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path


class SnapshotRejected(ValueError):
    pass


def load(path):
    p = Path(path)
    if not p.is_file():
        raise SnapshotRejected("MISSING:" + str(p))
    return json.loads(p.read_text(encoding="utf-8-sig"))


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _identity(request):
    if set(request.get("sources", {})) != {"PRTR"}:
        raise SnapshotRejected("ONLY_SCOPED_PRTR_REQUEST_ACCEPTED")
    cfg = request["sources"]["PRTR"]
    gate = cfg.get("identity_gate") or {}
    names = sorted({
        str(x).strip().casefold() for x in gate.get("current_entity_names", [])
        if str(x).strip()
    })
    company = str(request.get("company_display_name") or "").strip().casefold()
    if not company or not names or company not in names or gate.get("enabled") is not True:
        raise SnapshotRejected("VERIFIED_CURRENT_LEGAL_IDENTITY_REQUIRED")
    verified = sorted({
        str(site.get("address") or "").strip()
        for site in gate.get("verified_sites", [])
        if str(site.get("address") or "").strip()
    })
    # Keep exact verified identity constraints; never match a loose substring.
    return company, tuple(names), tuple(verified), int(cfg["start_year"]), int(cfg["end_year"])


def _rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate(current_source, archived_source, current_request, archive_request,
             archive_acceptance, *, run_id, collected_at, now=None, max_age_days=45):
    """Check metadata and every detail payload before allowing a copy."""
    current_source = Path(current_source)
    old = Path(archived_source)
    current_status = load(current_source / "status.json")
    if current_status.get("status") not in {"REMOTE_HOST_UNREACHABLE"}:
        raise SnapshotRejected("NOT_AN_EXPLICIT_RETRIEVAL_HOST_OUTAGE")
    if int(current_status.get("rows", 0) or 0) != 0:
        raise SnapshotRejected("PARTIAL_CURRENT_DATA_CANNOT_BE_OVERWRITTEN")
    if _identity(load(current_request)) != _identity(load(archive_request)):
        raise SnapshotRejected("COMPANY_SITE_OR_YEAR_SCOPE_MISMATCH")
    previous = load(old / "status.json")
    if (previous.get("status") != "DATA_FOUND"
            or int(previous.get("errors", 0) or 0)
            or int(previous.get("detail_fail", 0) or 0)):
        raise SnapshotRejected("ARCHIVE_COLLECTOR_NOT_COMPLETE")
    acceptance = load(archive_acceptance)
    if acceptance.get("status") != "PASS" or (acceptance.get("blocking_issues") or []):
        raise SnapshotRejected("ARCHIVE_ACCEPTANCE_NOT_PASS")
    try:
        observed = datetime.fromisoformat(str(collected_at).replace("Z", "+00:00"))
    except ValueError as e:
        raise SnapshotRejected("INVALID_ARCHIVE_CAPTURE_TIME") from e
    if observed.tzinfo is None:
        raise SnapshotRejected("CAPTURE_TIME_REQUIRES_TIMEZONE")
    now = now or datetime.now(timezone.utc)
    age = now - observed.astimezone(timezone.utc)
    if age < timedelta(seconds=-120) or age > timedelta(days=max_age_days):
        raise SnapshotRejected("ARCHIVED_EVIDENCE_TOO_OLD_OR_IN_FUTURE")
    cfg = load(current_request)["sources"]["PRTR"]
    years = set(range(int(cfg["start_year"]), int(cfg["end_year"]) + 1))
    records = _rows(old / "discovery.csv")
    if not records:
        raise SnapshotRejected("EMPTY_PRTR_DISCOVERY")
    try:
        found_years = {int(r["search_year"]) for r in records}
    except (KeyError, ValueError) as e:
        raise SnapshotRejected("INVALID_ARCHIVED_YEAR") from e
    if found_years != years:
        raise SnapshotRejected("ARCHIVE_REQUIRED_YEARS_NOT_COVERED")
    if int(previous.get("rows", -1)) != len(records):
        raise SnapshotRejected("ARCHIVE_DISCOVERY_ROW_COUNT_MISMATCH")
    if int(previous.get("detail_ok", -1)) != len(records):
        raise SnapshotRejected("ARCHIVE_DETAILS_INCOMPLETE")
    details = old / "detail_table_rows.jsonl"
    if not details.is_file():
        raise SnapshotRejected("ARCHIVE_DETAIL_LINES_MISSING")
    keys = set()
    with details.open(encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            keys.add((str(record.get("search_year")), str(record.get("entrps_id"))))
    if int(previous.get("detail_table_rows", -1)) < len(records):
        raise SnapshotRejected("ARCHIVE_DETAIL_STATUS_INCORRECT")
    for row in records:
        year, native_id = str(row["search_year"]), str(row["entrps_id"])
        if (year, native_id) not in keys:
            raise SnapshotRejected("ARCHIVE_DETAIL_ROW_NOT_FOUND:" + year)
        raw = old / "raw_detail" / f"{year}_{native_id}.html"
        if not raw.is_file() or raw.stat().st_size <= 5000:
            raise SnapshotRejected("ARCHIVE_DETAIL_HTML_MISSING:" + year)
    if not str(run_id).isdigit() or int(run_id) <= 0:
        raise SnapshotRejected("SOURCE_RUN_ID_REQUIRED")
    all_files = sorted(x for x in old.rglob("*") if x.is_file())
    digests = {x.relative_to(old).as_posix(): checksum(x) for x in all_files}
    return {
        "recovery_status": "VERIFIED_ORIGINAL_SNAPSHOT_REUSED",
        "source": "PRTR",
        "source_run_id": str(run_id),
        "source_captured_at": observed.astimezone(timezone.utc).isoformat(),
        "source_age_days": round(age.total_seconds() / 86400, 2),
        "current_failed_status": current_status["status"],
        "source_years": sorted(years),
        "source_native_ids": sorted({str(r["entrps_id"]) for r in records}),
        "source_row_count": len(records),
        "source_details_count": int(previous["detail_ok"]),
        "original_files_sha256": digests,
        "note": "과거 검증 원본 재사용. 이번 실행에서 PRTR 서버 재조회 성공을 의미하지 않습니다.",
    }


def recover(current_source, archived_source, current_request, archive_request,
            archive_acceptance, *, run_id, collected_at, now=None):
    receipt = validate(
        current_source, archived_source, current_request, archive_request,
        archive_acceptance, run_id=run_id, collected_at=collected_at, now=now,
    )
    dest = Path(current_source)
    src = Path(archived_source)
    backup = dest.parent / (dest.name + ".failed_fetch")
    if backup.exists():
        raise SnapshotRejected("RECOVERY_ALREADY_ATTEMPTED")
    shutil.move(str(dest), str(backup))
    try:
        shutil.copytree(src, dest)
        (dest / "source_snapshot_recovery.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(backup), str(dest))
        raise
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--current-source", required=True)
    p.add_argument("--snapshot-source", required=True)
    p.add_argument("--current-request", required=True)
    p.add_argument("--snapshot-request", required=True)
    p.add_argument("--snapshot-acceptance", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--collected-at", required=True)
    a = p.parse_args()
    try:
        result = recover(
            a.current_source, a.snapshot_source, a.current_request,
            a.snapshot_request, a.snapshot_acceptance,
            run_id=a.run_id, collected_at=a.collected_at,
        )
    except SnapshotRejected as e:
        print(json.dumps({"recovery_status": "REJECTED", "reason": str(e)},
                         ensure_ascii=False))
        return 2
    print(json.dumps({
        "recovery_status": result["recovery_status"],
        "source_run_id": result["source_run_id"],
        "original_retrieval_date": result["source_captured_at"],
        "source_row_count": result["source_row_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
