"""Recover ENV-INFO attachments after the collector hits its total storage budget.

The primary collector preserves broad source evidence but has a bounded attachment
storage budget. This recovery stage is intentionally generic:
- deduplicate already downloaded attachments by SHA-256;
- count the storage budget by unique physical bytes;
- retry only failures caused by the old total-budget condition;
- recover higher-value evidence first;
- bound recovery runtime so one large source cannot starve later collectors;
- checkpoint logical dedup references before deleting duplicate physical files;
- expose storage/time-budget skips explicitly instead of calling them download failures.
"""

import argparse
import csv
import json
import time
from pathlib import Path

import requests

try:
    from . import envinfo_collect as base
except ImportError:
    import envinfo_collect as base


RECOVERY_FIELDS = list(base.ATTACHMENT_FIELDS) + ["storage_state", "storage_reference"]
TOTAL_BUDGET_ERROR = "attachment collection size safety limit exceeded"
TIME_BUDGET_STATUS = "SKIPPED_RECOVERY_TIME_BUDGET"
DEFAULT_MAX_SECONDS = 360


class RecoveryTimeBudgetExceeded(RuntimeError):
    pass


def read_rows(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _atomic_text(path, text, encoding="utf-8"):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def write_rows(out, rows):
    """Atomically checkpoint attachment indexes.

    The CSV/JSONL checkpoint is written before any deduplicated physical file is
    deleted. A killed job can therefore leave harmless extra files, but never a
    manifest that still points at a file recovery already removed.
    """
    out = Path(out)
    fields = []
    for name in RECOVERY_FIELDS:
        if name not in fields:
            fields.append(name)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    csv_tmp = out / "attachment_index.csv.tmp"
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    csv_tmp.replace(out / "attachment_index.csv")

    jsonl = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    _atomic_text(out / "attachment_index.jsonl", jsonl)


def existing_file(row, repo_root):
    raw = str(row.get("stored_path") or "")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = Path(repo_root) / p
    return p if p.exists() else None


def deduplicate_downloaded(rows, repo_root="."):
    """Plan SHA dedup without deleting files.

    Returns duplicate physical paths separately. The caller must persist the updated
    logical references before deleting those paths. This ordering makes recovery safe
    when GitHub cancels a job at its wall-clock limit.
    """
    by_sha = {}
    unique_bytes = 0
    duplicate_rows = 0
    duplicate_bytes = 0
    duplicate_paths = []

    for row in rows:
        if row.get("collection_status") != "DOWNLOADED":
            continue
        p = existing_file(row, repo_root)
        if p is None:
            continue
        digest = str(row.get("sha256") or "") or base.sha256(p)
        count = int(row.get("bytes") or p.stat().st_size or 0)
        row["sha256"] = digest
        row["bytes"] = str(count)
        if digest not in by_sha:
            by_sha[digest] = str(p)
            unique_bytes += count
            row["storage_state"] = row.get("storage_state") or "UNIQUE_FILE"
            row["storage_reference"] = row.get("storage_reference") or ""
            continue

        canonical = Path(by_sha[digest])
        try:
            rel = canonical.resolve().relative_to(Path(repo_root).resolve())
            stored = str(rel)
        except ValueError:
            stored = str(canonical)
        if p.resolve() != canonical.resolve():
            duplicate_paths.append(p)
        row["stored_path"] = stored
        row["storage_state"] = "DEDUPLICATED_REFERENCE"
        row["storage_reference"] = stored
        duplicate_rows += 1
        duplicate_bytes += count

    return by_sha, unique_bytes, duplicate_rows, duplicate_bytes, duplicate_paths


def _delete_checkpointed_duplicates(paths):
    deleted = 0
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
            deleted += 1
        except OSError:
            # The logical manifest already points at the canonical file. A leftover
            # duplicate is storage overhead, not a broken reference.
            pass
    return deleted


def recovery_priority(row):
    """Prefer evidence needed for the human archive/study layer."""
    section = str(row.get("section_id") or "").lower()
    category = str(row.get("document_category") or "")
    importance = str(row.get("importance") or "")
    if section == "inquiry26":
        return (0, str(row.get("year") or ""), str(row.get("compId") or ""))
    if category in {"ENV_POLICY_GOAL", "CHEMICAL_MANAGEMENT", "EMERGENCY_RESPONSE", "INTERNAL_AUDIT", "ORGANIZATION_ROLE"}:
        return (1, str(row.get("year") or ""), str(row.get("compId") or ""))
    if importance == "CORE":
        return (2, str(row.get("year") or ""), str(row.get("compId") or ""))
    if importance == "SUPPORTING":
        return (3, str(row.get("year") or ""), str(row.get("compId") or ""))
    return (4, str(row.get("year") or ""), str(row.get("compId") or ""))


def _request_timeout(deadline, clock):
    if deadline is None:
        return (8, 60)
    remaining = deadline - clock()
    if remaining <= 0:
        raise RecoveryTimeBudgetExceeded("ENV-INFO attachment recovery time budget exhausted")
    return (max(0.5, min(8, remaining)), max(0.5, min(60, remaining)))


def download_without_total_cap(session, row, attachments_root, max_attempts=2, deadline=None, clock=time.monotonic):
    """Download one attachment with the per-file guard and optional deadline."""
    last_exc = None
    for attempt in range(max_attempts):
        target = None
        try:
            timeout = _request_timeout(deadline, clock)
            referer = f"{base.DETAIL}?YEAR={row['year']}&COMP_ID={row['compId']}&OPEN_YN=Y"
            r = session.post(
                base.DOWNLOAD,
                data={"FILE_ID": row["file_id"], "FILE_EXT": row["file_ext"]},
                headers={"Referer": referer, "Origin": base.BASE},
                timeout=timeout, stream=True, allow_redirects=True,
            )
            r.raise_for_status()
            declared = int(r.headers.get("Content-Length") or 0)
            if declared and declared > base.MAX_ATTACHMENT_BYTES:
                raise ValueError("attachment exceeds per-file safety limit")
            target = base.unique_target(
                Path(attachments_root) / str(row["year"]) / base.safe(row["compId"]),
                row["original_filename"], row["file_id"], row["file_ext"],
            )
            count = 0
            with target.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if deadline is not None and clock() >= deadline:
                        raise RecoveryTimeBudgetExceeded("ENV-INFO attachment recovery time budget exhausted")
                    if not chunk:
                        continue
                    count += len(chunk)
                    if count > base.MAX_ATTACHMENT_BYTES:
                        raise ValueError("attachment exceeds per-file safety limit")
                    f.write(chunk)
            if count == 0:
                raise ValueError("zero-byte attachment")
            ctype = str(r.headers.get("Content-Type") or "").split(";")[0].lower()
            if str(row.get("file_ext") or "").lower() not in {"html", "htm"} and ctype.startswith("text/html"):
                raise ValueError("attachment endpoint returned HTML instead of file")
            return target, count, base.sha256(target), ctype, attempt + 1
        except Exception as exc:
            last_exc = exc
            try:
                if target and target.exists():
                    target.unlink()
            except Exception:
                pass
            if isinstance(exc, RecoveryTimeBudgetExceeded):
                raise
            if attempt + 1 < max_attempts:
                if deadline is not None and clock() >= deadline:
                    raise RecoveryTimeBudgetExceeded("ENV-INFO attachment recovery time budget exhausted")
                time.sleep(0.5 * (attempt + 1))
    raise last_exc


def _mark_time_budget(rows):
    for row in rows:
        row.update({
            "stored_path": "",
            "collection_status": TIME_BUDGET_STATUS,
            "error": "Recovery runtime budget exhausted before this attachment was retried; source reference retained for later/manual retrieval.",
            "storage_state": "TIME_BUDGET_SKIPPED",
            "storage_reference": "",
        })


def recover(out_dir="output/ENVINFO", repo_root=".", total_limit=None, session=None, max_seconds=None, clock=time.monotonic):
    out = Path(out_dir)
    rows = read_rows(out / "attachment_index.csv")
    status_path = out / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    if not rows:
        return {"recovered": 0, "deduplicated": 0, "skipped_budget": 0, "skipped_time_budget": 0, "remaining_failed": 0}

    total_limit = int(total_limit or base.MAX_ATTACHMENT_TOTAL_BYTES)
    by_sha, unique_bytes, duplicate_rows, duplicate_bytes, duplicate_paths = deduplicate_downloaded(rows, repo_root)

    # Commit canonical references before physical cleanup. If the process is killed
    # afterwards, every manifest path still resolves; at worst duplicate files remain.
    if duplicate_paths:
        write_rows(out, rows)
        _delete_checkpointed_duplicates(duplicate_paths)

    candidates = [
        r for r in rows
        if r.get("collection_status") == "DOWNLOAD_FAILED"
        and TOTAL_BUDGET_ERROR in str(r.get("error") or "")
    ]
    candidates.sort(key=recovery_priority)

    max_seconds = None if max_seconds in (None, 0) else max(1, int(max_seconds))
    deadline = clock() + max_seconds if max_seconds is not None else None
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": base.UA})
    attachments_root = out / "raw_attachments"
    recovered = skipped_budget = skipped_time_budget = attempts_total = 0
    time_budget_exhausted = False

    for idx, row in enumerate(candidates):
        if deadline is not None and clock() >= deadline:
            remaining = candidates[idx:]
            _mark_time_budget(remaining)
            skipped_time_budget += len(remaining)
            time_budget_exhausted = True
            break
        try:
            target, count, digest, ctype, attempts = download_without_total_cap(
                sess, row, attachments_root, max_attempts=1, deadline=deadline, clock=clock
            )
            attempts_total += attempts
            if digest in by_sha:
                canonical = Path(by_sha[digest])
                target.unlink(missing_ok=True)
                try:
                    stored = str(canonical.resolve().relative_to(Path(repo_root).resolve()))
                except ValueError:
                    stored = str(canonical)
                row.update({
                    "stored_path": stored, "bytes": str(count), "sha256": digest, "content_type": ctype,
                    "collection_status": "DOWNLOADED", "error": "", "storage_state": "DEDUPLICATED_REFERENCE",
                    "storage_reference": stored,
                })
                recovered += 1
                continue

            if unique_bytes + count > total_limit:
                target.unlink(missing_ok=True)
                row.update({
                    "stored_path": "", "bytes": str(count), "sha256": digest, "content_type": ctype,
                    "collection_status": "SKIPPED_TOTAL_BUDGET",
                    "error": f"unique attachment storage budget exhausted: limit={total_limit}; used={unique_bytes}; candidate={count}",
                    "storage_state": "BUDGET_SKIPPED", "storage_reference": "",
                })
                skipped_budget += 1
                continue

            try:
                stored = str(target.resolve().relative_to(Path(repo_root).resolve()))
            except ValueError:
                stored = str(target)
            by_sha[digest] = str(target)
            unique_bytes += count
            row.update({
                "stored_path": stored, "bytes": str(count), "sha256": digest, "content_type": ctype,
                "collection_status": "DOWNLOADED", "error": "", "storage_state": "UNIQUE_FILE", "storage_reference": "",
            })
            recovered += 1
        except RecoveryTimeBudgetExceeded:
            remaining = candidates[idx:]
            _mark_time_budget(remaining)
            skipped_time_budget += len(remaining)
            time_budget_exhausted = True
            break
        except Exception as exc:
            row.update({"collection_status": "DOWNLOAD_FAILED", "error": f"{type(exc).__name__}: {exc}"})

    write_rows(out, rows)
    downloaded_rows = [r for r in rows if r.get("collection_status") == "DOWNLOADED"]
    remaining_failed = [r for r in rows if r.get("collection_status") == "DOWNLOAD_FAILED"]
    budget_skipped = [r for r in rows if r.get("collection_status") == "SKIPPED_TOTAL_BUDGET"]
    time_skipped = [r for r in rows if r.get("collection_status") == TIME_BUDGET_STATUS]
    logical_bytes = sum(int(r.get("bytes") or 0) for r in downloaded_rows)
    old_fail = int(status.get("attachment_fail") or 0)
    old_errors = int(status.get("errors") or 0)
    non_attachment_errors = max(0, old_errors - old_fail)
    status.update({
        "attachment_ok": len(downloaded_rows),
        "attachment_fail": len(remaining_failed),
        "attachment_skipped_budget": len(budget_skipped),
        "attachment_skipped_recovery_time_budget": len(time_skipped),
        "attachment_deduplicated": sum(1 for r in downloaded_rows if r.get("storage_state") == "DEDUPLICATED_REFERENCE"),
        "attachment_bytes": logical_bytes,
        "attachment_unique_bytes": unique_bytes,
        "attachment_duplicate_bytes_saved": duplicate_bytes,
        "attachment_recovery_attempts": attempts_total,
        "attachment_recovery_time_budget_seconds": max_seconds,
        "attachment_recovery_time_budget_exhausted": time_budget_exhausted,
        "errors": non_attachment_errors + len(remaining_failed),
    })
    _atomic_text(status_path, json.dumps(status, ensure_ascii=False, indent=2))
    summary = {
        "recovered": recovered,
        "deduplicated": duplicate_rows,
        "duplicate_bytes_saved": duplicate_bytes,
        "unique_bytes": unique_bytes,
        "skipped_budget": skipped_budget,
        "skipped_time_budget": skipped_time_budget,
        "time_budget_seconds": max_seconds,
        "time_budget_exhausted": time_budget_exhausted,
        "remaining_failed": len(remaining_failed),
        "attachment_ok": len(downloaded_rows),
    }
    _atomic_text(out / "attachment_recovery_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/ENVINFO")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--total-limit", type=int, default=base.MAX_ATTACHMENT_TOTAL_BYTES)
    ap.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS,
                    help="Soft wall-clock budget for recovery retries; 0 disables the limit.")
    args = ap.parse_args()
    recover(args.out, args.repo_root, args.total_limit, max_seconds=args.max_seconds)


if __name__ == "__main__":
    main()
