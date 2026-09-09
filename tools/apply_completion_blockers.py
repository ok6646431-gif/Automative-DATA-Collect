"""One-shot, idempotent patch for the final control-plane completion blockers."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "orchestrator/bat_collector.py"
RUNNER = ROOT / "orchestrator/zero_touch_runner.py"
ARCHIVE = ROOT / "orchestrator/archive_stage_core.py"
DOCS = ROOT / "requests/document_evidence.json"
TOKEN = ROOT / "requests/run_token.txt"

KRX_2025 = "https://kind.krx.co.kr/external/2026/07/24/000826/20260722001742/%EA%B8%88%ED%98%B8%EC%84%9D%EC%9C%A0%ED%99%94%ED%95%99%20%EC%A7%80%EC%86%8D%EA%B0%80%EB%8A%A5%EA%B2%BD%EC%98%81%EB%B3%B4%EA%B3%A0%EC%84%9C%202025.pdf"
KRX_2025_LOCATOR = "https://kind.krx.co.kr/external/2026/07/24/000826/20260722001742/99998.htm"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch target, found {count}")
    return text.replace(old, new, 1)


def patch_bat_runtime() -> None:
    text = BAT.read_text(encoding="utf-8")
    old = """import csv, hashlib, json, re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse
"""
    new = """import csv, hashlib, importlib.util, json, re, subprocess, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse


def _ensure_requests_runtime():
    # BAT collection runs in the final package job, which historically did not
    # install requests even though the collector imports it lazily. Self-bootstrap
    # the single missing runtime dependency rather than coupling BAT to workflow YAML.
    if importlib.util.find_spec('requests') is None:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', 'requests'],
            check=True,
        )
    if importlib.util.find_spec('requests') is None:
        raise RuntimeError('BAT HTTP runtime unavailable after requests installation')


_ensure_requests_runtime()
"""
    text = replace_once(text, old, new, "BAT requests runtime bootstrap")
    BAT.write_text(text, encoding="utf-8")


def patch_zero_touch_route_preservation() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    text = replace_once(text, "import re\nimport sys\n", "import json\nimport re\nimport sys\n", "zero-touch json import")
    old = """    discovery, documents, audit = g0_promotion_policy.apply(discovery, documents, audit)
    return discovery, documents, audit
"""
    new = """    discovery, documents, audit = g0_promotion_policy.apply(discovery, documents, audit)

    # Fresh Discovery owns document identity/coverage, but a stronger transport route
    # already byte-verified for the same DART-anchored legal entity must not disappear
    # merely because a later crawl rediscovers a weaker company-hosted URL.
    try:
        from orchestrator.document_route_merge import merge_document_routes
        existing_company_path = ROOT / 'requests/company_discovery.json'
        existing_documents_path = ROOT / 'requests/document_evidence.json'
        if existing_company_path.exists() and existing_documents_path.exists():
            existing_company = json.loads(existing_company_path.read_text(encoding='utf-8'))
            existing_documents = json.loads(existing_documents_path.read_text(encoding='utf-8'))
            before = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            documents = merge_document_routes(existing_company, existing_documents, discovery, documents)
            after = [str(x.get('source_url') or '') for x in documents.get('documents', []) or [] if isinstance(x, dict)]
            audit.setdefault('stages', {})['document_route_merge'] = {
                'status': 'APPLIED',
                'primary_routes_changed': sum(1 for a, b in zip(before, after) if a != b),
            }
    except Exception as exc:
        audit.setdefault('stages', {})['document_route_merge'] = {
            'status': 'SKIPPED_ERROR',
            'error': f'{type(exc).__name__}: {exc}',
        }
    return discovery, documents, audit
"""
    text = replace_once(text, old, new, "zero-touch repository route preservation")
    RUNNER.write_text(text, encoding="utf-8")


def patch_false_green_gate() -> None:
    text = ARCHIVE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    audit_collection_for_requested_scope(root, root/\"Company_Profile.json\", None, root/\"Document_Evidence.json\" if (root/\"Document_Evidence.json\").exists() else None)\n",
        "    completeness=audit_collection_for_requested_scope(root, root/\"Company_Profile.json\", None, root/\"Document_Evidence.json\" if (root/\"Document_Evidence.json\").exists() else None)\n",
        "archive completeness capture",
    )
    old = """    shutil.rmtree(root/"Human_Archive",ignore_errors=True)
    print(json.dumps({"archive_health":"PASS","archive":final,"validations_added":len(vals)},ensure_ascii=False))
    return final
"""
    new = """    shutil.rmtree(root/"Human_Archive",ignore_errors=True)
    print(json.dumps({"archive_health":"PASS","archive":final,"validations_added":len(vals),"collection_completeness":completeness},ensure_ascii=False))
    if str((completeness or {}).get('status') or '') != 'COMPLETE':
        raise RuntimeError(
            'COLLECTION_COMPLETENESS_GATE_FAILED: ' +
            json.dumps(completeness or {}, ensure_ascii=False)
        )
    return final
"""
    text = replace_once(text, old, new, "archive false-green completion gate")
    ARCHIVE.write_text(text, encoding="utf-8")


def seed_2025_route() -> None:
    data = json.loads(DOCS.read_text(encoding="utf-8"))
    matches = [d for d in data.get("documents", []) if str(d.get("document_type")) == "SUSTAINABILITY_REPORT" and str(d.get("report_year")) == "2025"]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one 2025 sustainability document, found {len(matches)}")
    doc = matches[0]
    if doc.get("source_url") != KRX_2025:
        previous = {
            "source_url": doc.get("source_url"),
            "source_locator": doc.get("source_locator"),
            "expected_extension": doc.get("expected_extension") or "pdf",
            "verification_status": doc.get("verification_status") or "SOURCE_VERIFIED",
            "source_role": "COMPANY_HOSTED_OFFICIAL",
            "notes": "Fresh official-company Discovery route retained as fallback after restoring the previously verified KRX delivery route.",
        }
        fallbacks = [x for x in (doc.get("fallback_sources") or []) if isinstance(x, dict)]
        urls = {str(x.get("source_url") or "") for x in fallbacks}
        if previous["source_url"] and previous["source_url"] not in urls:
            fallbacks.insert(0, previous)
        doc["fallback_sources"] = fallbacks
        doc["source_url"] = KRX_2025
        doc["source_locator"] = KRX_2025_LOCATOR
        doc["expected_extension"] = "pdf"
        doc["verification_status"] = "VERIFIED"
        note = str(doc.get("notes") or "").strip()
        extra = "Previously byte/transport-verified KRX disclosure attachment restored as primary; official company-hosted copy retained as fallback."
        doc["notes"] = (note + " " + extra).strip()
        doc["route_merge_status"] = "RESTORED_VERIFIED_PRIMARY"
    DOCS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    patch_bat_runtime()
    patch_zero_touch_route_preservation()
    patch_false_green_gate()
    seed_2025_route()
    TOKEN.write_text(
        "completion-fix:" + datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n",
        encoding="utf-8",
    )
    print("completion blockers patched in source code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
