"""Recover annual reports exposed by generic same-host JavaScript download controls.

The narrow scripted adapter supports a ``fileDownload(token)`` contract. Corporate
report libraries also use arbitrary function names and multiple literal arguments.
This adapter resolves only simple, statically inspectable contracts:

* a report-semantic DOM block supplies a year and a PDF/download control;
* the control invokes a JavaScript function with literal arguments;
* the function definition comes only from inline or same-host scripts;
* a URL expression built from literals and function parameters is reconstructed; and
* the reconstructed same-host target must return real PDF bytes.

No JavaScript is executed and no company-specific function/path is hard-coded.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

CALL_RE = re.compile(r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>.*?)\)", re.S)
FUNCTION_RE_TEMPLATE = r"function\s+{name}\s*\((?P<params>[^)]*)\)\s*\{{(?P<body>.{{0,6000}}?)\}}"
QUOTED_RE = re.compile(r"^\s*(['\"])(?P<value>(?:\\.|(?!\1).)*)\1\s*$", re.S)
URLISH_LITERAL_RE = re.compile(r"(?:https?://|/|\.pdf(?:\?|$)|download|file|attach|viewer)", re.I)
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


def _report_context(tag: Any) -> str:
    parts: List[str] = [" ".join(getattr(tag, "stripped_strings", []) or [])]
    node = tag
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = " ".join(getattr(node, "stripped_strings", []) or []).strip()
        if text:
            parts.append(text[:1200])
            low = text.casefold()
            if base._year_from(text) and any(token in low for token in REPORT_TOKENS):
                break
    return " ".join(_dedupe(parts))


def extract_report_controls(html: str, start_year: int, current_year: int) -> List[Dict[str, Any]]:
    """Extract literal JS function calls only from annual-report download controls."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all(True):
        label = " ".join(getattr(tag, "stripped_strings", []) or []).casefold()
        attrs = getattr(tag, "attrs", {}) or {}
        attr_text = " ".join(str(v) for v in attrs.values()).casefold()
        if not any(token in label or token in attr_text for token in DOWNLOAD_TOKENS):
            continue
        context = _report_context(tag)
        low = context.casefold()
        year = base._year_from(context)
        if not year or year < start_year or year > current_year:
            continue
        if not any(token in low for token in REPORT_TOKENS):
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
        for raw in raw_values:
            for name, args in extract_literal_calls(raw):
                out.append({
                    "year": int(year),
                    "function": name,
                    "args": args,
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


def _function_definition(name: str, scripts: Sequence[Tuple[str, str]]) -> Tuple[List[str], str, str] | None:
    pattern = re.compile(FUNCTION_RE_TEMPLATE.format(name=re.escape(name)), re.I | re.S)
    for source, text in scripts:
        match = pattern.search(text)
        if not match:
            continue
        params = [part.strip() for part in match.group("params").split(",") if part.strip()]
        return params, match.group("body"), source
    return None


def _split_concat(expr: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    quote_char = ""
    escape = False
    depth = 0
    for ch in str(expr or ""):
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
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "+" and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _eval_concat(expr: str, env: Mapping[str, str]) -> str | None:
    out: List[str] = []
    for token in _split_concat(str(expr or "").strip().rstrip(";")):
        literal = _literal_arg(token)
        if literal is not None:
            out.append(literal)
            continue
        name = token.strip()
        if name in env:
            out.append(str(env[name]))
            continue
        encoded = re.fullmatch(r"(?:encodeURIComponent|encodeURI)\s*\(\s*([A-Za-z_$][\w$]*)\s*\)", name)
        if encoded and encoded.group(1) in env:
            out.append(quote(str(env[encoded.group(1)]), safe=""))
            continue
        return None
    return "".join(out)


def reconstruct_targets(page_url: str, params: Sequence[str], args: Sequence[str], body: str) -> List[str]:
    """Reconstruct simple URL expressions from a function body without executing JS."""
    if len(params) != len(args):
        return []
    env = dict(zip(params, args))
    expressions: List[str] = []
    patterns = (
        r"(?:window\.)?location(?:\.href)?\s*=\s*(?P<expr>[^;\n]{1,1200})",
        r"(?:window\.)?open\s*\(\s*(?P<expr>[^,;\n]{1,1200})",
        r"(?:document\.)?location\.replace\s*\(\s*(?P<expr>[^);\n]{1,1200})",
        r"(?:url|action)\s*[:=]\s*(?P<expr>[^,;\n]{1,1200})",
    )
    for pattern in patterns:
        expressions.extend(match.group("expr") for match in re.finditer(pattern, body, re.I))
    targets: List[str] = []
    for expr in expressions:
        value = _eval_concat(expr, env)
        if not value or not URLISH_LITERAL_RE.search(value):
            continue
        target = urljoin(page_url, value)
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not base._same_org_host(target, page_url):
            continue
        targets.append(target)
    return _dedupe(targets)


def candidates_from_generic_js_page(
    http: Any,
    page_url: str,
    html: str,
    start_year: int,
    current_year: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    controls = extract_report_controls(html, start_year, current_year)
    if not controls:
        return [], []
    scripts = _script_texts(http, page_url, html)
    found: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()
    for control in controls:
        definition = _function_definition(control["function"], scripts)
        diagnostic = {
            **control,
            "function_definition_found": bool(definition),
            "candidate_targets": [],
        }
        diagnostics.append(diagnostic)
        if not definition:
            continue
        params, body, script_source = definition
        targets = reconstruct_targets(page_url, params, control["args"], body)
        diagnostic["script_source"] = script_source
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
                "year": control["year"],
                "label": context[:180],
                "url": final_url,
                "source_locator": page_url,
                "score": 105,
                "content_type": content_type,
                "download_contract": "VERIFIED_GENERIC_SAME_HOST_JS_FUNCTION",
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

    supporting = [
        d for d in documents.get("documents", []) or []
        if d.get("document_type") != "SUSTAINABILITY_REPORT"
    ]
    annual_by_year: Dict[int, Dict[str, Any]] = {}
    for d in documents.get("documents", []) or []:
        if d.get("document_type") == "SUSTAINABILITY_REPORT" and d.get("report_year"):
            annual_by_year[int(d["report_year"])] = d
    for candidate in sorted(recovered, key=lambda x: int(x.get("score") or 0), reverse=True):
        year = int(candidate["year"])
        if year in annual_by_year:
            continue
        annual_by_year[year] = {
            "document_id": f"AUTO_SUSTAINABILITY_{year}",
            "document_type": "SUSTAINABILITY_REPORT",
            "title": candidate["label"],
            "report_year": year,
            "source_url": candidate["url"],
            "source_locator": candidate["source_locator"],
            "expected_extension": "pdf",
            "verification_status": "SOURCE_VERIFIED",
            "importance": "CORE",
            "notes": "Annual-report DOM semantics + statically reconstructed same-org JavaScript download contract + streamed PDF byte verification.",
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
            "gap_id": f"AUTO_SUSTAINABILITY_{year}_UNRESOLVED",
            "source_key": "CORP_DOCS",
            "document_type": "SUSTAINABILITY_REPORT",
            "year": year,
            "verification_status": "UNVERIFIED",
            "status": "DISCOVERY_GAP",
            "severity": "MEDIUM",
            "blocking": True,
            "reason": "No byte-verified annual sustainability/integrated report was recovered from verified official report sources.",
            "source_locator": source_locator,
        })

    documents["documents"] = [*supporting, *[annual_by_year[y] for y in sorted(annual_by_year)]]
    documents["gaps"] = gaps
    documents["discovery_status"] = (
        "COMPLETE_FOR_DECLARED_PUBLIC_DOCUMENT_SCOPE"
        if not any(g.get("blocking") for g in gaps)
        else "PARTIAL"
    )
    audit.setdefault("stages", {})["generic_js_report_recovery"] = {
        "visited_pages": _dedupe(visited),
        "recovered_years": sorted({int(c["year"]) for c in recovered}),
        "recovered_candidate_count": len(recovered),
        "control_diagnostics": diagnostics[:80],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
