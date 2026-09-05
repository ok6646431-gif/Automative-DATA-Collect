"""Recover annual reports exposed by generic same-host JavaScript download controls.

Corporate report libraries use arbitrary function names, multiple literal arguments,
conditional URL construction, icon-only controls, direct ``window.open`` links, and
multi-year accordion pages. This adapter resolves only statically inspectable contracts:

* a report-semantic DOM block supplies local annual context;
* literal function arguments/direct targets may supply a stronger local year;
* function definitions come only from inline or same-host scripts;
* URL expressions built from literals and function parameters are reconstructed; and
* the reconstructed same-host target must return real PDF bytes.

No JavaScript is executed and no company-specific function/path is hard-coded.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_report_entity_policy as entity_policy
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

CALL_RE = re.compile(r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>.*?)\)", re.S)
QUOTED_RE = re.compile(r"^\s*(['\"])(?P<value>(?:\\.|(?!\1).)*)\1\s*$", re.S)
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
URLISH_LITERAL_RE = re.compile(r"(?:https?://|/|\.pdf(?:\?|$)|download|file|attach|viewer)", re.I)
DIRECT_TARGET_RE = re.compile(
    r"(?:window\.)?(?:open|location(?:\.href)?|location\.replace)\s*"
    r"(?:\(\s*|=\s*)(['\"])(?P<value>(?:\\.|(?!\1).)*)\1",
    re.I | re.S,
)
REPORT_TOKENS = (
    "지속가능경영보고서", "지속가능 보고서", "지속가능경영 보고서",
    "sustainability report", "integrated report", "esg report",
)
DOWNLOAD_TOKENS = ("pdf", "download", "다운로드")


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _split_js_args(raw: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    quote_char = ""
    escape = False
    depth = 0
    for ch in str(raw or ""):
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\" and quote_char:
            buf.append(ch)
            escape = True
            continue
        if quote_char:
            buf.append(ch)
            if ch == quote_char:
                quote_char = ""
            continue
        if ch in {"'", '"'}:
            quote_char = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf or str(raw or "").strip():
        parts.append("".join(buf).strip())
    return parts


def _literal_arg(value: str) -> str | None:
    m = QUOTED_RE.match(str(value or ""))
    if not m:
        return None
    raw = m.group("value")
    return (
        raw.replace(r"\/", "/")
        .replace(r"\'", "'")
        .replace(r'\"', '"')
        .replace(r"\\", "\\")
    )


def extract_literal_calls(raw: str) -> List[Tuple[str, List[str]]]:
    out: List[Tuple[str, List[str]]] = []
    for match in CALL_RE.finditer(str(raw or "")):
        args: List[str] = []
        valid = True
        for item in _split_js_args(match.group("args")):
            literal = _literal_arg(item)
            if literal is None:
                valid = False
                break
            args.append(literal)
        if valid and args:
            out.append((match.group("name"), args))
    return out


def extract_direct_literal_targets(raw: str) -> List[str]:
    out: List[str] = []
    for match in DIRECT_TARGET_RE.finditer(str(raw or "")):
        value = (
            match.group("value")
            .replace(r"\/", "/")
            .replace(r"\'", "'")
            .replace(r'\"', '"')
            .replace(r"\\", "\\")
        )
        if URLISH_LITERAL_RE.search(value):
            out.append(value)
    return _dedupe(out)


def _eligible_years(value: str, start_year: int, current_year: int) -> List[int]:
    return sorted({
        int(m.group(1)) for m in YEAR_RE.finditer(str(value or ""))
        if start_year <= int(m.group(1)) <= current_year
    })


def _local_report_context(tag: Any, start_year: int, current_year: int) -> Tuple[str, int | None]:
    """Use the nearest single-year report-semantic container, never a broad first year.

    Multi-year archive wrappers commonly contain every report year. Choosing the first
    year from such a wrapper silently re-labels deeper controls. We therefore walk from
    the control outward and accept a DOM-derived year only from the nearest container
    that contains report semantics and exactly one eligible year. A multi-year ancestor
    remains usable as semantic context when a literal JS argument/target supplies the
    year, but it is never itself a year selector.
    """
    fallback = ""
    node = tag
    for _ in range(7):
        if node is None:
            break
        text = " ".join(getattr(node, "stripped_strings", []) or []).strip()
        if text:
            low = text.casefold()
            if any(token in low for token in REPORT_TOKENS):
                years = _eligible_years(text, start_year, current_year)
                if len(years) == 1:
                    return text[:1200], years[0]
                if not fallback:
                    fallback = text[:1200]
        node = getattr(node, "parent", None)
    return fallback, None


def _control_literal_year(raw_values: Sequence[str], start_year: int, current_year: int) -> int | None:
    """Prefer an unambiguous year encoded in the control's own literal contract."""
    years: set[int] = set()
    for raw in raw_values:
        for _, args in extract_literal_calls(raw):
            for arg in args:
                years.update(_eligible_years(arg, start_year, current_year))
        for target in extract_direct_literal_targets(raw):
            years.update(_eligible_years(target, start_year, current_year))
    return next(iter(years)) if len(years) == 1 else None


def _has_download_signal(tag: Any, label: str, attr_text: str) -> bool:
    if any(token in label or token in attr_text for token in DOWNLOAD_TOKENS):
        return True
    for child in getattr(tag, "find_all", lambda *a, **k: [])(True):
        attrs = getattr(child, "attrs", {}) or {}
        descendant_attrs = " ".join(str(v) for v in attrs.values()).casefold()
        if any(token in descendant_attrs for token in DOWNLOAD_TOKENS):
            return True
    return False


def extract_report_controls(html: str, start_year: int, current_year: int) -> List[Dict[str, Any]]:
    """Extract literal JS calls/targets only from annual-report download controls."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all(True):
        label = " ".join(getattr(tag, "stripped_strings", []) or []).casefold()
        attrs = getattr(tag, "attrs", {}) or {}
        attr_text = " ".join(str(v) for v in attrs.values()).casefold()
        if not _has_download_signal(tag, label, attr_text):
            continue

        raw_values: List[str] = []
        for key, value in attrs.items():
            key_low = str(key).casefold()
            if (
                key_low in {"onclick", "onmousedown", "onmouseup", "href", "data-action", "data-click", "data-url"}
                or key_low.startswith("data-")
            ):
                if isinstance(value, (list, tuple)):
                    raw_values.extend(str(x) for x in value)
                else:
                    raw_values.append(str(value))
        if not raw_values:
            continue

        context, dom_year = _local_report_context(tag, start_year, current_year)
        if not context or not any(token in context.casefold() for token in REPORT_TOKENS):
            continue
        literal_year = _control_literal_year(raw_values, start_year, current_year)
        year = literal_year or dom_year
        if not year:
            continue

        for raw in raw_values:
            direct_targets = extract_direct_literal_targets(raw)
            for target in direct_targets:
                out.append({
                    "year": int(year),
                    "year_evidence": "CONTROL_LITERAL" if literal_year else "LOCAL_DOM",
                    "function": "",
                    "args": [],
                    "direct_targets": [target],
                    "context": context[:1000],
                    "raw_control": raw[:1000],
                })
            for name, args in extract_literal_calls(raw):
                if name.casefold() in {"open", "replace"} and direct_targets:
                    continue
                out.append({
                    "year": int(year),
                    "year_evidence": "CONTROL_LITERAL" if literal_year else "LOCAL_DOM",
                    "function": name,
                    "args": args,
                    "direct_targets": [],
                    "context": context[:1000],
                    "raw_control": raw[:1000],
                })
    unique: List[Dict[str, Any]] = []
    seen: set[Tuple[int, str, Tuple[str, ...], Tuple[str, ...]]] = set()
    for item in out:
        key = (
            item["year"], item["function"], tuple(item["args"]),
            tuple(item.get("direct_targets") or []),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _script_texts(http: Any, page_url: str, html: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    host = base._host(page_url)
    out: List[Tuple[str, str]] = []
    for script in soup.find_all("script"):
        if not script.get("src"):
            text = script.string or script.get_text() or ""
            if text.strip():
                out.append((page_url, text))
    for script in soup.find_all("script", src=True)[:50]:
        url = urljoin(page_url, str(script.get("src") or ""))
        if base._host(url) != host:
            continue
        response = http.get(url)
        if not response or response.status_code >= 400:
            continue
        out.append((response.url or url, response.text))
    return out


def _balanced_function_body(text: str, brace_index: int, max_chars: int = 16000) -> str | None:
    depth = 0
    quote_char = ""
    escape = False
    line_comment = False
    block_comment = False
    end = min(len(text), brace_index + max_chars)
    for i in range(brace_index, end):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < end else ""
        if line_comment:
            if ch in "\r\n":
                line_comment = False
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
            continue
        if escape:
            escape = False
            continue
        if quote_char:
            if ch == "\\":
                escape = True
            elif ch == quote_char:
                quote_char = ""
            continue
        if ch in {"'", '"', "`"}:
            quote_char = ch
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1:i]
    return None


def _function_definition(name: str, scripts: Sequence[Tuple[str, str]]) -> Tuple[List[str], str, str] | None:
    header = re.compile(
        rf"function\s+{re.escape(name)}\s*\((?P<params>[^)]*)\)\s*\{{", re.I | re.S
    )
    for source, text in scripts:
        match = header.search(text)
        if not match:
            continue
        body = _balanced_function_body(text, match.end() - 1)
        if body is None:
            continue
        params = [part.strip() for part in match.group("params").split(",") if part.strip()]
        return params, body, source
    return None


def _split_concat(expr: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    quote_char = ""
    escape = False
    depth = 0
    for ch in str(expr or ""):
        if escape:
            buf.append(ch); escape = False; continue
        if ch == "\\" and quote_char:
            buf.append(ch); escape = True; continue
        if quote_char:
            buf.append(ch)
            if ch == quote_char:
                quote_char = ""
            continue
        if ch in {"'", '"'}:
            quote_char = ch; buf.append(ch); continue
        if ch == "(": depth += 1
        elif ch == ")": depth = max(0, depth - 1)
        if ch == "+" and depth == 0:
            parts.append("".join(buf).strip()); buf = []; continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _eval_concat(expr: str, env: Mapping[str, str]) -> str | None:
    out: List[str] = []
    for token in _split_concat(str(expr or "").strip().rstrip(";")):
        literal = _literal_arg(token)
        if literal is not None:
            out.append(literal); continue
        name = token.strip()
        if name in env:
            out.append(str(env[name])); continue
        encoded = re.fullmatch(r"(?:encodeURIComponent|encodeURI)\s*\(\s*([A-Za-z_$][\w$]*)\s*\)", name)
        if encoded and encoded.group(1) in env:
            out.append(quote(str(env[encoded.group(1)]), safe="")); continue
        return None
    return "".join(out)


def reconstruct_targets(page_url: str, params: Sequence[str], args: Sequence[str], body: str) -> List[str]:
    if len(params) != len(args):
        return []
    env = dict(zip(params, args))
    expressions: List[str] = []
    patterns = (
        r"(?:window\.)?location(?:\.href)?\s*=\s*(?P<expr>[^;\n]{1,1200})",
        r"(?:window\.)?open\s*\(\s*(?P<expr>[^,;\n]{1,1200})",
        r"(?:document\.)?location\.replace\s*\(\s*(?P<expr>[^);\n]{1,1200})",
        r"(?:var\s+|let\s+|const\s+)?(?:url|action)\s*[:=]\s*(?P<expr>[^,;\n]{1,1200})",
    )
    for pattern in patterns:
        expressions.extend(m.group("expr") for m in re.finditer(pattern, body, re.I))
    targets: List[str] = []
    for expr in expressions:
        value = _eval_concat(expr, env)
        if not value or not URLISH_LITERAL_RE.search(value):
            continue
        target = urljoin(page_url, value)
        parsed = urlparse(target)
        if parsed.scheme in {"http", "https"} and base._same_org_host(target, page_url):
            targets.append(target)
    return _dedupe(targets)


def candidates_from_generic_js_page(
    http: Any, page_url: str, html: str, start_year: int, current_year: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    controls = extract_report_controls(html, start_year, current_year)
    if not controls:
        return [], []
    scripts = _script_texts(http, page_url, html)
    found: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()
    for control in controls:
        function_name = str(control.get("function") or "")
        definition = _function_definition(function_name, scripts) if function_name else None
        direct_targets = [urljoin(page_url, x) for x in (control.get("direct_targets") or [])]
        diagnostic = {**control, "function_definition_found": bool(definition), "candidate_targets": list(direct_targets)}
        diagnostics.append(diagnostic)
        targets = list(direct_targets)
        if definition:
            params, body, script_source = definition
            targets.extend(reconstruct_targets(page_url, params, control["args"], body))
            diagnostic["script_source"] = script_source
        targets = _dedupe(targets)
        diagnostic["candidate_targets"] = targets
        for target in targets:
            if target in seen_targets:
                continue
            seen_targets.add(target)
            ok, final_url, content_type = scripted._verify_pdf(http, target, page_url)
            if not ok:
                continue
            context = control["context"]
            if not strict.strong_report_semantics(context, final_url, page_url):
                continue
            found.append({
                "year": control["year"], "label": context[:180], "url": final_url,
                "source_locator": page_url, "score": 105, "content_type": content_type,
                "year_evidence": control.get("year_evidence"),
                "download_contract": (
                    "VERIFIED_DIRECT_SAME_HOST_JS_TARGET"
                    if direct_targets and target in direct_targets
                    else "VERIFIED_GENERIC_SAME_HOST_JS_FUNCTION"
                ),
            })
            break
    return found, diagnostics


def _report_pages(audit: Dict[str, Any]) -> List[str]:
    pages: List[str] = []
    corporate = ((audit.get("stages") or {}).get("corporate_documents") or {})
    pages.extend(corporate.get("report_index_pages") or [])
    navigation = ((audit.get("stages") or {}).get("scripted_report_navigation_recovery") or {})
    pages.extend(navigation.get("visited_pages") or [])
    return _dedupe([
        p for p in pages
        if any(token in str(p).casefold() for token in ("report", "보고", "esg", "sustain"))
    ])


def _existing_report_blocks_recovery(discovery: Dict[str, Any], doc: Dict[str, Any]) -> bool:
    title = str(doc.get("title") or "")
    url = str(doc.get("source_url") or "")
    if entity_policy.is_summary_representation(title, url):
        return False
    alignment, _ = entity_policy.entity_alignment(discovery, title, url)
    return alignment != "CONFLICT"


def enrich(discovery: Dict[str, Any], documents: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    policy = discovery.get("collection_policy") or {}
    window = policy.get("requested_history_window") or {}
    start_year = int(window.get("start_year") or 2020)
    current_year = int(window.get("end_year") or 2026)
    http = base.Http()
    recovered: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    visited: List[str] = []
    for page_url in _report_pages(audit)[:24]:
        response = http.get(page_url)
        if not response or response.status_code >= 400:
            continue
        visited.append(response.url)
        candidates, page_diagnostics = candidates_from_generic_js_page(
            http, response.url, response.text, start_year, current_year
        )
        recovered.extend(candidates)
        diagnostics.extend(page_diagnostics)

    supporting: List[Dict[str, Any]] = []
    annual_by_year: Dict[int, Dict[str, Any]] = {}
    for d in documents.get("documents", []) or []:
        if d.get("document_type") != "SUSTAINABILITY_REPORT":
            supporting.append(d); continue
        if not _existing_report_blocks_recovery(discovery, d):
            supporting.append(d); continue
        if d.get("report_year"):
            annual_by_year[int(d["report_year"])] = d
        else:
            supporting.append(d)

    for candidate in sorted(recovered, key=lambda x: int(x.get("score") or 0), reverse=True):
        year = int(candidate["year"])
        if year in annual_by_year:
            continue
        annual_by_year[year] = {
            "document_id": f"AUTO_SUSTAINABILITY_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": candidate["label"], "report_year": year,
            "source_url": candidate["url"], "source_locator": candidate["source_locator"],
            "expected_extension": "pdf", "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": "Annual-report DOM semantics + local-year evidence + statically reconstructed same-org JavaScript download contract + streamed PDF byte verification.",
        }

    found_years = set(annual_by_year)
    old_gaps = {
        int(g.get("year")): g for g in documents.get("gaps", []) or []
        if g.get("document_type") == "SUSTAINABILITY_REPORT" and g.get("year")
    }
    gaps = [g for g in documents.get("gaps", []) or [] if g.get("document_type") != "SUSTAINABILITY_REPORT"]
    source_locator = visited[0] if visited else ""
    for year in range(start_year, current_year + 1):
        if year in found_years:
            continue
        gaps.append(old_gaps.get(year) or {
            "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED", "source_key": "CORP_DOCS",
            "document_type": "SUSTAINABILITY_REPORT", "year": year,
            "verification_status": "UNVERIFIED", "status": "DISCOVERY_GAP",
            "severity": "MEDIUM", "blocking": True,
            "reason": "No byte-verified annual sustainability/integrated report was recovered from verified official report sources.",
            "source_locator": source_locator,
        })

    documents["documents"] = [*supporting, *[annual_by_year[y] for y in sorted(annual_by_year)]]
    documents["gaps"] = gaps
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in gaps) else "PARTIAL"
    )
    audit.setdefault("stages", {})["generic_js_report_recovery"] = {
        "visited_pages": _dedupe(visited),
        "recovered_years": sorted({int(c["year"]) for c in recovered}),
        "recovered_candidate_count": len(recovered),
        "control_diagnostics": diagnostics[:80],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
