"""Recover annual reports exposed by JavaScript-driven GET form submissions.

Some first-party report archives use an inert annual-report button whose literal
JavaScript call writes a file identifier into a form field, selects a form option and
clicks a submit control.  This adapter statically follows that HTML/JavaScript contract
without executing JavaScript and without inventing a vendor-specific download path.

A candidate is accepted only when:
* the control is inside a nearest single-year annual-report DOM context;
* the JavaScript call and its arguments are literal and statically inspectable;
* the called function writes a literal argument into a named control in a same-page
  GET form and explicitly submits/clicks that form;
* the reconstructed form action stays on the same organization host; and
* following that GET request returns real PDF bytes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_generic_js_report_recovery as generic
from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

VAL_SET_RE = re.compile(
    r"\$\(\s*(['\"])#(?P<id>[A-Za-z_][\w:.-]*)\1\s*\)"
    r"\.val\(\s*(?P<param>[A-Za-z_$][\w$]*)\s*\)",
    re.I,
)
CHECKED_PROP_RE = re.compile(
    r"\$\(\s*(['\"])#(?P<id>[A-Za-z_][\w:.-]*)\1\s*\)"
    r"\.(?:prop|attr)\(\s*(['\"])checked\2\s*,\s*(?:true|(['\"])checked\3)\s*\)",
    re.I,
)
TRIGGER_RE = re.compile(
    r"\$\(\s*(['\"])#(?P<id>[A-Za-z_][\w:.-]*)\1\s*\)"
    r"\.(?P<action>click|submit)\s*\(\s*\)",
    re.I,
)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def extract_form_report_controls(
    html: str,
    start_year: int,
    current_year: int,
) -> List[Dict[str, Any]]:
    """Return literal JS calls bound to one local annual-report year.

    Unlike the ordinary generic-JS adapter, no download keyword is required on the
    button itself.  The stronger gate is the nearest single-year report context plus a
    literal function call; the eventual target must still pass same-host and PDF-byte
    verification before it can become evidence.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all(["a", "button", "input"]):
        attrs = dict(getattr(tag, "attrs", {}) or {})
        raw_values: List[str] = []
        for key in ("onclick", "onmousedown", "onmouseup", "href", "data-action", "data-click"):
            value = attrs.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                raw_values.extend(str(x) for x in value)
            else:
                raw_values.append(str(value))
        for key, value in attrs.items():
            if not str(key).casefold().startswith("data-"):
                continue
            if isinstance(value, (list, tuple)):
                raw_values.extend(str(x) for x in value)
            else:
                raw_values.append(str(value))
        if not raw_values:
            continue

        context, dom_year = generic._local_report_context(tag, start_year, current_year)
        if not context or dom_year is None:
            continue
        if not any(token in context.casefold() for token in generic.REPORT_TOKENS):
            continue

        literal_year = generic._control_literal_year(raw_values, start_year, current_year)
        year = literal_year or dom_year
        label = " ".join(getattr(tag, "stripped_strings", []) or []).strip()
        for raw in raw_values:
            for function_name, args in generic.extract_literal_calls(raw):
                # Browser built-ins and direct URL calls belong to the ordinary JS
                # adapter.  Here a named page function must be resolved to a form.
                if function_name.casefold() in {"open", "replace", "void"}:
                    continue
                out.append({
                    "year": int(year),
                    "year_evidence": "CONTROL_LITERAL" if literal_year else "LOCAL_DOM",
                    "function": function_name,
                    "args": args,
                    "label": label,
                    "context": context[:1000],
                    "raw_control": raw[:1000],
                })

    unique: List[Dict[str, Any]] = []
    seen: set[Tuple[int, str, Tuple[str, ...]]] = set()
    for item in out:
        key = (item["year"], item["function"], tuple(item["args"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _form_for_trigger(soup: BeautifulSoup, trigger_id: str, action: str) -> Any | None:
    node = soup.find(id=trigger_id)
    if node is None:
        return None
    if str(action or "").casefold() == "submit" and getattr(node, "name", "") == "form":
        return node
    if str(action or "").casefold() == "click":
        node_type = str(node.get("type") or "").casefold()
        if getattr(node, "name", "") in {"input", "button"} and node_type in {"submit", "image"}:
            return node.find_parent("form")
    return None


def reconstruct_get_form_targets(
    page_url: str,
    html: str,
    params: Sequence[str],
    args: Sequence[str],
    body: str,
) -> List[str]:
    """Reconstruct only explicit same-page GET form submissions from a function body."""
    if len(params) != len(args):
        return []
    env: Mapping[str, str] = dict(zip(params, args))
    value_bindings = {m.group("id"): m.group("param") for m in VAL_SET_RE.finditer(body)}
    if not value_bindings or not any(param in env for param in value_bindings.values()):
        return []
    checked_ids = {m.group("id") for m in CHECKED_PROP_RE.finditer(body)}
    triggers = [(m.group("id"), m.group("action")) for m in TRIGGER_RE.finditer(body)]
    if not triggers:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    targets: List[str] = []
    for trigger_id, trigger_action in triggers:
        form = _form_for_trigger(soup, trigger_id, trigger_action)
        if form is None:
            continue
        method = str(form.get("method") or "get").casefold().strip()
        action = str(form.get("action") or "").strip()
        if method != "get" or not action:
            continue
        target_base = urljoin(page_url, action)
        parsed = urlparse(target_base)
        if parsed.scheme not in {"http", "https"} or not base._same_org_host(target_base, page_url):
            continue

        query: List[Tuple[str, str]] = []
        bound_argument = False
        for control in form.find_all(["input", "select", "textarea"]):
            name = str(control.get("name") or "").strip()
            control_id = str(control.get("id") or "").strip()
            if not name:
                continue
            if control_id in value_bindings:
                param = value_bindings[control_id]
                if param not in env:
                    continue
                query.append((name, str(env[param])))
                bound_argument = True
                continue
            if control_id in checked_ids:
                query.append((name, str(control.get("value") or "on")))
        if not bound_argument:
            continue
        separator = "&" if parsed.query else "?"
        targets.append(target_base + separator + urlencode(query, doseq=True))
    return _dedupe(targets)


def candidates_from_js_form_page(
    http: Any,
    page_url: str,
    html: str,
    start_year: int,
    current_year: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    controls = extract_form_report_controls(html, start_year, current_year)
    if not controls:
        return [], []
    scripts = generic._script_texts(http, page_url, html)
    found: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()

    for control in controls:
        definition = generic._function_definition(control["function"], scripts)
        diagnostic = {
            **control,
            "function_definition_found": bool(definition),
            "candidate_targets": [],
        }
        diagnostics.append(diagnostic)
        if not definition:
            continue
        params, body, script_source = definition
        targets = reconstruct_get_form_targets(
            page_url, html, params, control["args"], body
        )
        diagnostic["script_source"] = script_source
        diagnostic["candidate_targets"] = targets
        for target in targets:
            if target in seen_targets:
                continue
            seen_targets.add(target)
            ok, final_url, content_type = scripted._verify_pdf(http, target, page_url)
            diagnostic["pdf_magic_verified"] = bool(ok)
            diagnostic["final_url"] = final_url
            diagnostic["content_type"] = content_type
            if not ok:
                continue
            if not strict.strong_report_semantics(control["context"], final_url, page_url):
                continue
            score = 116
            low_label = str(control.get("label") or "").casefold()
            if any(x in low_label for x in ("kor", "korean", "국문")):
                score += 5
            elif any(x in low_label for x in ("eng", "english", "영문")):
                score += 2
            found.append({
                "year": int(control["year"]),
                "label": f"{control['year']} sustainability report {control.get('label') or ''}".strip(),
                "url": final_url,
                "source_locator": page_url,
                "score": score,
                "content_type": content_type,
                "year_evidence": control.get("year_evidence"),
                "download_contract": "VERIFIED_GENERIC_SAME_HOST_JS_GET_FORM",
            })
            break
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
        candidates, page_diagnostics = candidates_from_js_form_page(
            http, response.url, response.text, start_year, current_year
        )
        recovered.extend(candidates)
        diagnostics.extend(page_diagnostics)

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
            "document_id": f"AUTO_SUSTAINABILITY_JS_FORM_{candidate['year']}_{len(added)+1}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": candidate["label"],
            "report_year": int(candidate["year"]),
            "source_url": candidate["url"],
            "source_locator": candidate["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": (
                "Nearest single-year official report DOM context + literal JavaScript call + "
                "statically reconstructed same-org GET form submission + streamed PDF magic verification."
            ),
        }
        documents.setdefault("documents", []).append(item)
        added.append(item)

    audit.setdefault("stages", {})["js_form_report_recovery"] = {
        "visited_pages": _dedupe(visited),
        "recovered_years": sorted({int(x["year"]) for x in recovered}),
        "recovered_candidate_count": len(recovered),
        "added_document_count": len(added),
        "control_diagnostics": diagnostics[:80],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
