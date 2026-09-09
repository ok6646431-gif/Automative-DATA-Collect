"""One-shot, idempotent patch for the final control-plane completion blockers."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECT = ROOT / ".github/workflows/collect.yml"
ZERO = ROOT / ".github/workflows/zero-touch-discovery.yml"
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


def patch_collect() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "run: python -m pip install --disable-pip-version-check xlsxwriter beautifulsoup4 pypdf openpyxl",
        "run: python -m pip install --disable-pip-version-check requests xlsxwriter beautifulsoup4 pypdf openpyxl",
        "package requests dependency",
    )
    gate = """      - name: Enforce final delivery contract
        if: always()
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          errors=[]
          completeness=Path('assembled/Collection_Completeness.json')
          if not completeness.is_file():
              errors.append('missing assembled/Collection_Completeness.json')
          else:
              payload=json.loads(completeness.read_text(encoding='utf-8'))
              status=str(payload.get('status') or '')
              if not status.startswith('COMPLETE'):
                  errors.append(f'collection completeness is {status or "UNKNOWN"}')
          human=Path('assembled/Human_Archive.zip')
          if not human.is_file() or human.stat().st_size == 0:
              errors.append('missing or empty Human_Archive.zip')
          app=list(Path('application-delivery').glob('*.zip')) if Path('application-delivery').exists() else []
          if not any(p.is_file() and p.stat().st_size > 0 for p in app):
              errors.append('missing application-materials zip')
          if errors:
              raise SystemExit('FINAL_DELIVERY_CONTRACT_FAILED: ' + '; '.join(errors))
          print('FINAL_DELIVERY_CONTRACT_PASS')
          PY
"""
    marker = "      - name: Publish control-plane run receipt\n"
    if "      - name: Enforce final delivery contract\n" not in text:
        if marker not in text:
            raise RuntimeError("final delivery gate insertion marker missing")
        text = text.replace(marker, gate + marker, 1)
    COLLECT.write_text(text, encoding="utf-8")


def patch_zero_touch() -> None:
    text = ZERO.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "      - 'orchestrator/zero_touch_runner.py'\n",
        "      - 'orchestrator/document_route_merge.py'\n      - 'orchestrator/zero_touch_runner.py'\n",
        "zero-touch module trigger",
    )
    text = replace_once(
        text,
        "      - 'tests/test_document_evidence_schema.py'\n",
        "      - 'tests/test_document_evidence_schema.py'\n      - 'tests/test_document_route_merge.py'\n",
        "zero-touch test trigger",
    )
    text = replace_once(
        text,
        "orchestrator/g0_thin_shell_recovery.py orchestrator/zero_touch_runner.py",
        "orchestrator/g0_thin_shell_recovery.py orchestrator/document_route_merge.py orchestrator/zero_touch_runner.py",
        "zero-touch py_compile",
    )
    text = replace_once(
        text,
        "          python -m unittest tests.test_document_evidence_schema -v\n",
        "          python -m unittest tests.test_document_evidence_schema -v\n          python -m unittest tests.test_document_route_merge -v\n",
        "zero-touch route merge regression",
    )
    old = """          cp generated-discovery/company_discovery.json "$promo_dir/company_discovery.json"
          cp generated-discovery/document_evidence.json "$promo_dir/document_evidence.json"
          cp generated-discovery/event_evidence.json "$promo_dir/event_evidence.json"
"""
    new = """          cp generated-discovery/company_discovery.json "$promo_dir/company_discovery.json"
          python orchestrator/document_route_merge.py \\
            --existing-company requests/company_discovery.json \\
            --existing-documents requests/document_evidence.json \\
            --fresh-company generated-discovery/company_discovery.json \\
            --fresh-documents generated-discovery/document_evidence.json \\
            --out "$promo_dir/document_evidence.json"
          cp generated-discovery/event_evidence.json "$promo_dir/event_evidence.json"
"""
    text = replace_once(text, old, new, "zero-touch route merge promotion")
    ZERO.write_text(text, encoding="utf-8")


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
    patch_collect()
    patch_zero_touch()
    seed_2025_route()
    TOKEN.write_text(
        "completion-fix:" + datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n",
        encoding="utf-8",
    )
    print("completion blockers patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
