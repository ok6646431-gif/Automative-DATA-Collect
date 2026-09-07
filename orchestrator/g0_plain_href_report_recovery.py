"""Recover annual reports exposed as ordinary same-host download hrefs.

Some official report archives use JavaScript for historical reports but ordinary
``<a href="...download...">KOR</a>`` links for the current report. The target can be
opaque and even carry a broken content-type, so URL semantics alone are insufficient.

This adapter remains fail-closed:
* the anchor must sit inside a nearest single-year annual-report DOM context;
* the href must stay in the same official organization;
* labels that clearly denote supporting derivatives (Factbook, Highlight, etc.) are
  excluded; and
* the target must return real PDF magic bytes under the official page Referer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_generic_js_report_recovery as generic
from orchestrator import g0_js_form_report_recovery
from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

SUPPORTING_LABEL_TOKENS = (
    "factbook", "fact book", "appendix", "하이라이트", "highlight", "summary", "요약",
    "policybook", "policy book", "오디오북", "audiobook", "audio book", "data book", "databook",
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _supporting_label(label: str) -> bool:
    low = str(label or "").casefold()
    return any(token in low for token in SUPPORTING_LABEL_TOKENS)


def candidates_from_plain_href_page(
    http: Any,
    page_url: str,
    html: str,
    start_year: int,
    current_year: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        label = " ".join(anchor.stripped_strings).strip()
        attr_text = " ".join(str(v) for v in (anchor.attrs or {}).values()).casefold()
        if _supporting_label(label):
            continue
        if not generic._has_download_signal(anchor, label.casefold(), attr_text):
            continue

        context, year = generic._local_report_context(anchor, start_year, current_year)
        if not context or not year:
            continue
        if not any(token in context.casefold() for token in generic.REPORT_TOKENS):
            continue

        target = urljoin(page_url, href)
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not base._same_org_host(target, page_url):
            continue
        if target in seen_targets:
            continue
        seen_targets.add(target)

        diagnostic = {
            "year": int(year),
            "year_evidence": "LOCAL_DOM",
            "label": label,
            "target": target,
            "source_locator": page_url,
        }
        diagnostics.append(diagnostic)

        ok, final_url, content_type = scripted._verify_pdf(http, target, page_url)
        diagnostic["pdf_magic_verified"] = bool(ok)
        diagnostic["final_url"] = final_url
        diagnostic["content_type"] = content_type
        if not ok:
            continue
        if not strict.strong_report_semantics(context, final_url, page_url):
            continue

        score = 110
        low_label = label.casefold()
        if any(x in low_label for x in ("kor", "korean", "국문")):
            score += 5
        if any(x in low_label for x in ("eng", "english", "영문")):
            score += 2
        found.append({
            "year": int(year),
            "label": f"{year} sustainability report" if not label else f"{year} sustainability report {label}",
            "url": final_url,
            "source_locator": page_url,
            "score": score,
            "content_type": content_type,
            "download_contract": "VERIFIED_PLAIN_SAME_ORG_HREF_LOCAL_YEAR",
        })

    return found, diagnostics


def _report_pages(audit: Dict[str, Any]) -> List[str]:
    pages: List[str] = []
    strict_stage = (audit.get("stages") or {}).get("strict_report_enrichment") or {}
    pages.extend(strict_stage.get("trusted_secondary_starts") or [])
    pages.extend(generic._report_pages(audit))
    return _dedupe(pages)


def enrich(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    current_year = int(window.get("end_year") or start_year)

    http = base.Http(timeout=(6, 18))
    recovered: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    visited: List[str] = []
    for page_url in _report_pages(audit)[:24]:
        response = http.get(page_url)
        if not response or response.status_code >= 400:
            continue
        visited.append(response.url)
        candidates, page_diagnostics = candidates_from_plain_href_page(
            http, response.url, response.text, start_year, current_year
        )
        recovered.extend(candidates)
        diagnostics.extend(page_diagnostics)

    # Keep all recovered candidates here. The downstream entity policy arbitrates
    # issuer conflicts and same-year precedence, so a same-group report discovered
    # elsewhere cannot block a requested-entity candidate at this stage.
    recovered.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    existing_keys = {
        (str(d.get("source_url") or ""), str(d.get("report_year") or ""))
        for d in documents.get("documents", []) or []
    }
    added: List[Dict[str, Any]] = []
    for candidate in recovered:
        key = (str(candidate["url"]), str(candidate["year"]))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        item = {
            "document_id": f"AUTO_SUSTAINABILITY_PLAIN_HREF_{candidate['year']}_{len(added)+1}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": candidate["label"],
            "report_year": int(candidate["year"]),
            "source_url": candidate["url"],
            "source_locator": candidate["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": (
                "Nearest single-year official report DOM context + ordinary same-org href + "
                "supporting-label exclusion + streamed PDF magic verification."
            ),
        }
        documents.setdefault("documents", []).append(item)
        added.append(item)

    audit.setdefault("stages", {})["plain_href_report_recovery"] = {
        "visited_pages": _dedupe(visited),
        "recovered_years": sorted({int(x["year"]) for x in recovered}),
        "recovered_candidate_count": len(recovered),
        "added_document_count": len(added),
        "control_diagnostics": diagnostics[:80],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)

    # Historical libraries can expose neighboring years through an inert JavaScript
    # button that submits a same-page GET form rather than through href/data-* URLs.
    # Run that contract as a separate audited adapter so plain-href semantics stay
    # unchanged and the downstream entity/finalizer policies remain the sole arbiters.
    return g0_js_form_report_recovery.enrich(discovery, documents, audit)
