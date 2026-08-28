"""Fail-closed replay of ICIS sources after a verified remote-host outage.

Fresh collection always wins.  When every live ICIS attempt is unusable for one or
more sources, this module may reuse a recent, previously successful raw collector
artifact only when the source-specific query fingerprint is identical.  Replayed
sources retain their original source status but are explicitly marked stale/reused
so package validation can degrade the run and require human review.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

try:
    from .company_profile_builder import compile_discovery
    from .request_builder import build
except ImportError:  # script execution
    from company_profile_builder import compile_discovery
    from request_builder import build


BAD = {"REMOTE_HOST_UNREACHABLE", "REQUEST_OR_PARSE_FAILED", "CONFIG_ERROR", "COLLECTION_FAILED_RETRY_EXHAUSTED"}
SOURCES = ("PRTR", "CHEM_STATS")
REPLAY_FRESHNESS = "REPLAYED_LAST_KNOWN_GOOD"
FRESH_FRESHNESS = "FRESH_CURRENT_RUN"
FINGERPRINT_VERSION = "icis-query-v1"


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _sorted_texts(values: Iterable[Any]) -> List[str]:
    return sorted({_norm_text(v) for v in (values or []) if _norm_text(v)})


def source_query_payload(request: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Return only fields that can change what the collector asks or how rows map.

    Delays/retry timing are deliberately excluded: changing a throttle should not
    invalidate otherwise identical source data.  Address anchors are included for
    PRTR because they affect proposed site identity in the collector output.
    """
    cfg = copy.deepcopy((request.get("sources") or {}).get(source) or {})
    company = _norm_text(request.get("company_display_name") or request.get("company_name") or "")

    if source == "PRTR":
        specs = []
        for item in cfg.get("search_terms") or []:
            if isinstance(item, dict):
                specs.append(
                    {
                        "term": _norm_text(item.get("term")),
                        "year_start": item.get("year_start"),
                        "year_end": item.get("year_end"),
                    }
                )
            else:
                specs.append({"term": _norm_text(item), "year_start": None, "year_end": None})
        specs.sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
        anchors = {
            str(k): _sorted_texts(v if isinstance(v, list) else [v])
            for k, v in sorted((cfg.get("site_address_anchors") or {}).items())
        }
        payload = {
            "fingerprint_version": FINGERPRINT_VERSION,
            "source": source,
            "company_display_name": company,
            "start_year": cfg.get("start_year"),
            "end_year": cfg.get("end_year"),
            "search_terms": specs,
            "exclude_terms": _sorted_texts(cfg.get("exclude_terms") or []),
            "site_address_anchors": anchors,
            "max_pages": int(cfg.get("max_pages", 50)),
            "collect_details": bool(cfg.get("collect_details", True)),
        }
    elif source == "CHEM_STATS":
        by_year = {
            str(k): _sorted_texts(v if isinstance(v, list) else [v])
            for k, v in sorted((cfg.get("search_terms_by_year") or {}).items(), key=lambda kv: str(kv[0]))
        }
        payload = {
            "fingerprint_version": FINGERPRINT_VERSION,
            "source": source,
            "company_display_name": company,
            "years": sorted(int(x) for x in (cfg.get("years") or [2024])),
            "search_terms": _sorted_texts(cfg.get("search_terms") or [company]),
            "search_terms_by_year": by_year,
            "exclude_terms": _sorted_texts(cfg.get("exclude_terms") or []),
            "max_pages": int(cfg.get("max_pages", 10)),
            "collect_details": bool(cfg.get("collect_details", True)),
        }
    else:
        raise ValueError(f"unsupported source: {source}")
    return payload


def source_fingerprint(request: Dict[str, Any], source: str) -> str:
    raw = json.dumps(source_query_payload(request, source), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_root(root: Path) -> Optional[Path]:
    for candidate in (root, root / "output"):
        if (candidate / "PRTR" / "status.json").exists() or (candidate / "CHEM_STATS" / "status.json").exists():
            return candidate
    return None


def _status(root: Path, source: str) -> Optional[Dict[str, Any]]:
    path = root / source / "status.json"
    if not path.exists():
        return None
    try:
        return _read_json(path)
    except Exception:
        return None


def _is_good_status(status: Optional[Dict[str, Any]]) -> bool:
    return bool(status and status.get("status") not in BAD)


def _copy_source(src_root: Path, dst_root: Path, source: str) -> None:
    src = src_root / source
    dst = dst_root / source
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _candidate_source_complete(root: Path, source: str, status: Dict[str, Any]) -> Tuple[bool, str]:
    src = root / source
    if not src.is_dir():
        return False, "missing_source_directory"
    if status.get("freshness") == REPLAY_FRESHNESS or int(status.get("replay_chain_depth") or 0) > 0:
        return False, "candidate_is_already_replayed"
    if not _is_good_status(status):
        return False, f"candidate_status_{status.get('status')}"
    if status.get("status") == "DATA_FOUND":
        discovery = src / "discovery.csv"
        if not discovery.exists() or discovery.stat().st_size == 0:
            return False, "data_found_without_discovery"
        if int(status.get("detail_ok") or 0) > 0:
            raw_detail = src / "raw_detail"
            if not raw_detail.is_dir() or not any(p.is_file() and p.stat().st_size > 0 for p in raw_detail.iterdir()):
                return False, "detail_ok_without_raw_detail"
    return True, "ok"


def stamp_artifact(request_path: Path, root: Path, run_id: str, head_sha: str, artifact_label: str) -> Dict[str, Any]:
    request = _read_json(request_path)
    meta = root / "_replay"
    meta.mkdir(parents=True, exist_ok=True)
    shutil.copy2(request_path, meta / "request.json")
    sources: Dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    for source in SOURCES:
        st = _status(root, source)
        sources[source] = {
            "query_fingerprint": source_fingerprint(request, source),
            "source_status": (st or {}).get("status", "MISSING_STATUS"),
            "freshness": FRESH_FRESHNESS if _is_good_status(st) else "UNAVAILABLE_CURRENT_RUN",
        }
    manifest = {
        "schema_version": "icis-replay-cache-1.0",
        "generated_at": now,
        "origin_run_id": str(run_id or ""),
        "origin_head_sha": str(head_sha or ""),
        "artifact_label": str(artifact_label or ""),
        "sources": sources,
    }
    _write_json(meta / "cache_manifest.json", manifest)
    return manifest


def _natural_attempt_dirs(attempts_root: Path) -> List[Path]:
    dirs = [p for p in attempts_root.iterdir() if p.is_dir()] if attempts_root.exists() else []
    def key(p: Path) -> Tuple[int, str]:
        digits = "".join(ch for ch in p.name if ch.isdigit())
        return (int(digits) if digits else 0, p.name)
    return sorted(dirs, key=key)


def _pick_current_sources(attempts_root: Path, out: Path) -> Tuple[Dict[str, bool], Dict[str, Dict[str, Any]]]:
    attempts = _natural_attempt_dirs(attempts_root)
    good = {s: False for s in SOURCES}
    latest_status: Dict[str, Dict[str, Any]] = {}

    # Preserve the latest observable state first so a blocked replay remains explicit.
    for source in SOURCES:
        for attempt in reversed(attempts):
            root = _source_root(attempt)
            if not root:
                continue
            st = _status(root, source)
            if st:
                latest_status[source] = st
                _copy_source(root, out, source)
                break

    # Fresh success wins source-by-source, using the latest successful attempt.
    for source in SOURCES:
        for attempt in reversed(attempts):
            root = _source_root(attempt)
            if not root:
                continue
            st = _status(root, source)
            if _is_good_status(st):
                _copy_source(root, out, source)
                stamped = _read_json(out / source / "status.json")
                stamped["freshness"] = FRESH_FRESHNESS
                stamped["current_attempt"] = attempt.name
                _write_json(out / source / "status.json", stamped)
                good[source] = True
                latest_status[source] = stamped
                break
    return good, latest_status


def _github_get(session: requests.Session, url: str) -> Any:
    r = session.get(url, timeout=(8, 30))
    r.raise_for_status()
    return r.json()


def _download_zip(session: requests.Session, url: str) -> bytes:
    r = session.get(url, timeout=(8, 90), allow_redirects=True)
    r.raise_for_status()
    return r.content


def _safe_extract(data: bytes, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            dest = (target / info.filename).resolve()
            if base != dest and base not in dest.parents:
                raise ValueError(f"unsafe zip member: {info.filename}")
        zf.extractall(target)


def _git_json(head_sha: str, path: str) -> Optional[Dict[str, Any]]:
    try:
        raw = subprocess.check_output(["git", "show", f"{head_sha}:{path}"], stderr=subprocess.DEVNULL)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _request_for_head(head_sha: str) -> Optional[Dict[str, Any]]:
    discovery = _git_json(head_sha, "requests/company_discovery.json")
    if discovery:
        try:
            profile, _ = compile_discovery(discovery)
            profile["requested_scope"] = discovery.get("requested_scope") or {"mode": "COMPANY"}
            return build(profile)
        except Exception:
            return None
    profile = _git_json(head_sha, "requests/company_profile.json")
    if profile:
        try:
            return build(profile)
        except Exception:
            return None
    return None


def _candidate_request(root: Path, head_sha: str) -> Optional[Dict[str, Any]]:
    cached = root / "_replay" / "request.json"
    if cached.exists():
        try:
            return _read_json(cached)
        except Exception:
            return None
    return _request_for_head(head_sha)


def replay(
    current_request_path: Path,
    attempts_root: Path,
    out: Path,
    repository: str,
    token: str,
    current_run_id: str,
    workflow_id: str,
    branch: str,
    max_age_days: int = 30,
    candidate_limit: int = 12,
) -> Dict[str, Any]:
    current_request = _read_json(current_request_path)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    good, latest = _pick_current_sources(attempts_root, out)
    missing = [s for s in SOURCES if not good[s]]
    decision: Dict[str, Any] = {
        "schema_version": "icis-replay-decision-1.0",
        "replayed_at": datetime.now(timezone.utc).isoformat(),
        "current_run_id": str(current_run_id),
        "branch": branch,
        "max_age_days": int(max_age_days),
        "fresh_sources": [s for s in SOURCES if good[s]],
        "missing_before_replay": list(missing),
        "replayed_sources": [],
        "candidate_checks": [],
    }
    if not missing:
        decision["decision"] = "FRESH_DATA_COMPLETE"
        _write_json(out / "_replay" / "decision.json", decision)
        return decision

    if not token or not repository or not workflow_id:
        decision["decision"] = "REPLAY_BLOCKED_NO_GITHUB_CONTEXT"
        _write_json(out / "_replay" / "decision.json", decision)
        return decision

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "enterprise-env-icis-replay/1.0",
        }
    )
    api = f"https://api.github.com/repos/{repository}"
    try:
        current_meta = _github_get(session, f"{api}/actions/runs/{current_run_id}")
        current_created = datetime.fromisoformat(current_meta["created_at"].replace("Z", "+00:00"))
        runs_obj = _github_get(
            session,
            f"{api}/actions/workflows/{workflow_id}/runs?branch={requests.utils.quote(branch, safe='')}&per_page=50",
        )
    except Exception as exc:
        decision["decision"] = "REPLAY_BLOCKED_GITHUB_LOOKUP_FAILED"
        decision["lookup_error"] = f"{type(exc).__name__}: {exc}"
        _write_json(out / "_replay" / "decision.json", decision)
        return decision

    runs = []
    for run in runs_obj.get("workflow_runs") or []:
        if str(run.get("id")) == str(current_run_id):
            continue
        if run.get("conclusion") != "success":
            continue
        try:
            created = datetime.fromisoformat(str(run.get("created_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        if created >= current_created:
            continue
        age_days = (current_created - created).total_seconds() / 86400.0
        if age_days > max_age_days:
            continue
        runs.append((created, run))
    runs.sort(key=lambda item: item[0], reverse=True)

    checked_artifacts = 0
    for _, run in runs:
        if not missing or checked_artifacts >= candidate_limit:
            break
        try:
            art_obj = _github_get(session, f"{api}/actions/runs/{run['id']}/artifacts?per_page=100")
        except Exception as exc:
            decision["candidate_checks"].append({"run_id": run.get("id"), "result": "artifact_list_failed", "error": str(exc)})
            continue
        artifacts = [a for a in (art_obj.get("artifacts") or []) if not a.get("expired")]
        # Never replay a replay artifact.  Prefer the latest fresh collector attempt.
        priority = {"icis-attempt-3": 3, "icis-attempt-2": 2, "icis-attempt-1": 1}
        artifacts = [a for a in artifacts if a.get("name") in priority]
        artifacts.sort(key=lambda a: priority.get(a.get("name"), 0), reverse=True)
        for artifact in artifacts:
            if not missing or checked_artifacts >= candidate_limit:
                break
            checked_artifacts += 1
            check: Dict[str, Any] = {
                "run_id": run.get("id"),
                "run_number": run.get("run_number"),
                "head_sha": run.get("head_sha"),
                "artifact_id": artifact.get("id"),
                "artifact_name": artifact.get("name"),
                "artifact_digest": artifact.get("digest"),
                "source_results": {},
            }
            try:
                data = _download_zip(session, artifact["archive_download_url"])
                with tempfile.TemporaryDirectory(prefix="icis-replay-") as td:
                    root = Path(td)
                    _safe_extract(data, root)
                    src_root = _source_root(root)
                    candidate_req = _candidate_request(root, str(run.get("head_sha") or ""))
                    if not src_root or not candidate_req:
                        check["result"] = "candidate_structure_or_request_missing"
                        decision["candidate_checks"].append(check)
                        continue
                    for source in list(missing):
                        st = _status(src_root, source)
                        ok, why = _candidate_source_complete(src_root, source, st or {})
                        current_fp = source_fingerprint(current_request, source)
                        candidate_fp = source_fingerprint(candidate_req, source)
                        source_result = {
                            "candidate_status": (st or {}).get("status"),
                            "candidate_complete": ok,
                            "candidate_check": why,
                            "fingerprint_match": current_fp == candidate_fp,
                            "current_fingerprint": current_fp,
                            "candidate_fingerprint": candidate_fp,
                        }
                        check["source_results"][source] = source_result
                        if not ok or current_fp != candidate_fp:
                            continue
                        _copy_source(src_root, out, source)
                        replay_status = _read_json(out / source / "status.json")
                        current_failure = latest.get(source) or {}
                        replay_status["freshness"] = REPLAY_FRESHNESS
                        replay_status["replay_chain_depth"] = 1
                        replay_status["replay_provenance"] = {
                            "origin_run_id": str(run.get("id") or ""),
                            "origin_run_number": run.get("run_number"),
                            "origin_head_sha": str(run.get("head_sha") or ""),
                            "origin_artifact_id": str(artifact.get("id") or ""),
                            "origin_artifact_name": artifact.get("name"),
                            "origin_artifact_digest": artifact.get("digest"),
                            "origin_created_at": run.get("created_at"),
                            "reused_at": decision["replayed_at"],
                            "current_failure_status": current_failure.get("status"),
                            "current_failure_reason": current_failure.get("preflight_error") or current_failure.get("fatal_error") or current_failure.get("failure_reason"),
                            "query_fingerprint": current_fp,
                            "fingerprint_version": FINGERPRINT_VERSION,
                        }
                        _write_json(out / source / "status.json", replay_status)
                        good[source] = True
                        missing.remove(source)
                        decision["replayed_sources"].append(source)
                    check["result"] = "accepted" if any(v.get("fingerprint_match") and v.get("candidate_complete") for v in check["source_results"].values()) else "not_eligible"
            except Exception as exc:
                check["result"] = "candidate_download_or_validation_failed"
                check["error"] = f"{type(exc).__name__}: {exc}"
            decision["candidate_checks"].append(check)

    # Mark any still-unavailable current source with a compact replay decision so
    # packaging preserves why stale reuse was refused instead of silently omitting it.
    for source in missing:
        sp = out / source / "status.json"
        if sp.exists():
            st = _read_json(sp)
            st["replay_attempt"] = {
                "decision": "NO_ELIGIBLE_LAST_KNOWN_GOOD",
                "checked_artifacts": checked_artifacts,
                "max_age_days": max_age_days,
                "fingerprint_version": FINGERPRINT_VERSION,
            }
            _write_json(sp, st)

    decision["missing_after_replay"] = list(missing)
    decision["decision"] = "REPLAY_APPLIED" if decision["replayed_sources"] else "NO_ELIGIBLE_REPLAY"
    if decision["replayed_sources"] and missing:
        decision["decision"] = "PARTIAL_REPLAY_APPLIED"
    _write_json(out / "_replay" / "decision.json", decision)
    return decision


def main() -> None:
    ap = argparse.ArgumentParser(description="Stamp or safely replay ICIS collector artifacts")
    sub = ap.add_subparsers(dest="command", required=True)

    stamp = sub.add_parser("stamp")
    stamp.add_argument("--request", required=True)
    stamp.add_argument("--root", default="output")
    stamp.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    stamp.add_argument("--head-sha", default=os.getenv("GITHUB_SHA", ""))
    stamp.add_argument("--artifact-label", default="")

    rp = sub.add_parser("replay")
    rp.add_argument("--current-request", required=True)
    rp.add_argument("--attempts-root", required=True)
    rp.add_argument("--out", default="replay-output")
    rp.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    rp.add_argument("--token", default=os.getenv("GH_TOKEN", ""))
    rp.add_argument("--current-run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    rp.add_argument("--workflow-id", default=os.getenv("GITHUB_WORKFLOW_REF", ""))
    rp.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", ""))
    rp.add_argument("--max-age-days", type=int, default=30)
    rp.add_argument("--candidate-limit", type=int, default=12)

    args = ap.parse_args()
    if args.command == "stamp":
        result = stamp_artifact(Path(args.request), Path(args.root), args.run_id, args.head_sha, args.artifact_label)
    else:
        workflow_id = args.workflow_id
        # GITHUB_WORKFLOW_REF is a path@ref, not a numeric id. Workflow jobs pass the
        # numeric id explicitly; reject ambiguous defaults rather than guessing.
        if workflow_id and not str(workflow_id).isdigit():
            workflow_id = ""
        result = replay(
            Path(args.current_request),
            Path(args.attempts_root),
            Path(args.out),
            args.repository,
            args.token,
            args.current_run_id,
            workflow_id,
            args.branch,
            args.max_age_days,
            args.candidate_limit,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
