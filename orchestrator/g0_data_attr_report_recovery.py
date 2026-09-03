"""Recover annual reports from data-attribute driven JavaScript download controls.

Some corporate report libraries attach file metadata to DOM controls (``data-*``)
and register a shared jQuery click handler that derives a viewer/download URL.  This
adapter never executes JavaScript. It accepts a contract only when all of the following
are visible in first-party HTML/scripts:

* the control is inside a strong annual-report context and exposes PDF-like metadata;
* one of the control's CSS classes is bound to a click handler on the same page;
* the handler reads those exact ``data-*`` attributes and statically constructs a URL;
* the reconstructed URL stays on the same organization host; and
* fetching it returns real PDF bytes.

The parser is intentionally small and fail-closed. It supports literal concatenation,
local variables derived from ``$(this).data(...)``, and common substring operations
used to split a stored filename into stem/extension. No company, class, attribute, or
path value is hard-coded.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from orchestrator import g0_report_enrichment as strict
from orchestrator import g0_scripted_report_enrichment as scripted
from orchestrator import zero_touch_discovery as base

REPORT_TOKENS = (
    "지속가능경영보고서", "지속가능경영 보고서", "지속가능 보고서",
    "sustainability report", "integrated report", "esg report",
)
DOWNLOAD_TOKENS = ("pdf", "download", "다운로드")
DATA_ACCESS_RE = re.compile(
    r"\$\(\s*this\s*\)\.data\(\s*['\"](?P<key>[A-Za-z0-9_-]+)['\"]\s*\)", re.I
)
ASSIGN_RE = re.compile(
    r"(?:var|let|const)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>[^;\n]{1,2400})\s*;",
    re.I,
)
OPEN_RE = re.compile(r"(?:window\.)?open\s*\(\s*(?P<expr>[^,;\n]{1,2400})", re.I)
LOCATION_RE = re.compile(r"(?:window\.)?location(?:\.href)?\s*=\s*(?P<expr>[^;\n]{1,2400})", re.I)
QUOTED_RE = re.compile(r"^\s*(['\"])(?P<value>(?:\\.|(?!\1).)*)\1\s*$", re.S)


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _literal(value: str) -> str | None:
    m = QUOTED_RE.match(str(value or ""))
    if not m:
        return None
    return (
        m.group("value")
        .replace(r"\/", "/")
        .replace(r"\'", "'")
        .replace(r'\"', '"')
        .replace(r"\\", "\\")
    )


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


def _report_context(tag: Any) -> str:
    parts: List[str] = [" ".join(getattr(tag, "stripped_strings", []) or [])]
    node = tag
    for _ in range(7):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = " ".join(getattr(node, "stripped_strings", []) or []).strip()
        if not text:
            continue
        parts.append(text[:1600])
        low = text.casefold()
        if base._year_from(text) and any(token in low for token in REPORT_TOKENS):
            break
    return " ".join(_dedupe(parts))


def extract_data_controls(html: str, start_year: int, current_year: int) -> List[Dict[str, Any]]:
    """Return annual-report controls that expose usable first-party ``data-*`` metadata."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all(True):
        attrs = dict(getattr(tag, "attrs", {}) or {})
        data_attrs: Dict[str, str] = {}
        for key, value in attrs.items():
            key_s = str(key)
            if not key_s.casefold().startswith("data-"):
                continue
            if isinstance(value, (list, tuple)):
                value = " ".join(str(v) for v in value)
            data_attrs[key_s[5:]] = str(value or "").strip()
        if not data_attrs:
            continue
        label = " ".join(getattr(tag, "stripped_strings", []) or [])
        blob = (label + " " + " ".join(data_attrs.values())).casefold()
        if not any(token in blob for token in DOWNLOAD_TOKENS):
            continue
        # At least one declared data value must itself identify a PDF; otherwise generic
        # data-* UI widgets are not considered report-download candidates.
        if not any(str(v).casefold().endswith(".pdf") for v in data_attrs.values()):
            continue
        context = _report_context(tag)
        low = context.casefold()
        year = base._year_from(context)
        if not year or year < start_year or year > current_year:
            continue
        if not any(token in low for token in REPORT_TOKENS):
            continue
        classes = [str(x) for x in (attrs.get("class") or []) if str(x).strip()]
        if not classes:
            continue
        out.append({
            "year": int(year),
            "classes": classes,
            "data": data_attrs,
            "context": context[:1200],
        })
    unique: List[Dict[str, Any]] = []
    seen: set[Tuple[int, Tuple[str, ...], Tuple[Tuple[str, str], ...]]] = set()
    for item in out:
        key = (
            item["year"],
            tuple(sorted(item["classes"])),
            tuple(sorted(item["data"].items())),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _inline_scripts(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    return [
        (script.string or script.get_text() or "")
        for script in soup.find_all("script")
        if not script.get("src") and (script.string or script.get_text() or "").strip()
    ]


def _handler_for_class(class_name: str, scripts: Sequence[str]) -> str | None:
    """Find a bounded jQuery click-handler body for one exact CSS class selector."""
    selector = re.escape("." + str(class_name))
    patterns = (
        rf"\$\(\s*['\"]{selector}['\"]\s*\)\.on\(\s*['\"]click['\"]\s*,\s*function\s*\([^)]*\)\s*\{{(?P<body>.{{0,8000}}?)\n\s*\}}\s*\)\s*;?",
        rf"jQuery\(\s*['\"]{selector}['\"]\s*\)\.on\(\s*['\"]click['\"]\s*,\s*function\s*\([^)]*\)\s*\{{(?P<body>.{{0,8000}}?)\n\s*\}}\s*\)\s*;?",
    )
    for text in scripts:
        for pattern in patterns:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                return m.group("body")
    return None


def _data_value(expr: str, data: Mapping[str, str]) -> str | None:
    """Evaluate a small whitelist of ``$(this).data(...)`` string transforms."""
    source = str(expr or "").strip()
    direct = DATA_ACCESS_RE.fullmatch(source)
    if direct:
        return data.get(direct.group("key"))

    # data('x').substring(0, data('x').indexOf('.'))
    m = re.fullmatch(
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P<key>[\w-]+)['\"]\s*\)\.substring\(\s*0\s*,\s*"
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P=key)['\"]\s*\)\.indexOf\(\s*['\"](?P<sep>[^'\"]+)['\"]\s*\)\s*\)",
        source, re.I,
    )
    if m and m.group("key") in data:
        value = data[m.group("key")]
        idx = value.find(m.group("sep"))
        return value[:idx] if idx >= 0 else value

    # data('x').substring(0, data('x').lastIndexOf('.'))
    m = re.fullmatch(
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P<key>[\w-]+)['\"]\s*\)\.substring\(\s*0\s*,\s*"
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P=key)['\"]\s*\)\.lastIndexOf\(\s*['\"](?P<sep>[^'\"]+)['\"]\s*\)\s*\)",
        source, re.I,
    )
    if m and m.group("key") in data:
        value = data[m.group("key")]
        idx = value.rfind(m.group("sep"))
        return value[:idx] if idx >= 0 else value

    # data('x').substring(data('x').indexOf('.') + N)
    m = re.fullmatch(
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P<key>[\w-]+)['\"]\s*\)\.substring\(\s*"
        r"\$\(\s*this\s*\)\.data\(\s*['\"](?P=key)['\"]\s*\)\.indexOf\(\s*['\"](?P<sep>[^'\"]+)['\"]\s*\)\s*\+\s*(?P<n>\d+)\s*\)",
        source, re.I,
    )
    if m and m.group("key") in data:
        value = data[m.group("key")]
        idx = value.find(m.group("sep"))
        if idx < 0:
            return ""
        return value[idx + int(m.group("n")):]
    return None


def _eval_concat(expr: str, env: Mapping[str, str], data: Mapping[str, str]) -> str | None:
    out: List[str] = []
    for atom in _split_concat(str(expr or "").strip().rstrip(";")):
        literal = _literal(atom)
        if literal is not None:
            out.append(literal)
            continue
        name = atom.strip()
        if name in env:
            out.append(str(env[name]))
            continue
        value = _data_value(name, data)
        if value is not None:
            out.append(value)
            continue
        return None
    return "".join(out)


def reconstruct_data_targets(page_url: str, data: Mapping[str, str], handler_body: str) -> List[str]:
    """Statically evaluate local data-derived variables and final viewer URL expressions."""
    # The handler must actually consume declared data attributes; this prevents using a
    # coincidental class handler that is unrelated to the control's file metadata.
    used_keys = {m.group("key") for m in DATA_ACCESS_RE.finditer(handler_body)}
    if not used_keys.intersection(data):
        return []

    env: Dict[str, str] = {}
    assignments = list(ASSIGN_RE.finditer(handler_body))
    # Resolve simple local expressions in source order, retrying because URL variables
    # can depend on variables declared a few statements earlier.
    for _ in range(4):
        changed = False
        for match in assignments:
            name = match.group("name")
            if name in env:
                continue
            expr = match.group("expr")
            value = _data_value(expr, data)
            if value is None:
                value = _eval_concat(expr, env, data)
            if value is not None:
                env[name] = value
                changed = True
        if not changed:
            break

    expressions: List[str] = []
    expressions.extend(m.group("expr") for m in OPEN_RE.finditer(handler_body))
    expressions.extend(m.group("expr") for m in LOCATION_RE.finditer(handler_body))
    # Also consider URL-like local assignments that are later passed by variable name.
    for match in assignments:
        if re.search(r"url|uri|href|link|viewer|download|file", match.group("name"), re.I):
            expressions.append(match.group("name"))

    targets: List[str] = []
    for expr in expressions:
        value = env.get(expr.strip())
        if value is None:
            value = _eval_concat(expr, env, data)
        if not value or "/" not in value:
            continue
        target = urljoin(page_url, value)
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        if not base._same_org_host(target, page_url):
            continue
        targets.append(target)
    return _dedupe(targets)


def candidates_from_data_attr_page(
    http: Any,
    page_url: str,
    html: str,
    start_year: int,
    current_year: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    controls = extract_data_controls(html, start_year, current_year)
    scripts = _inline_scripts(html)
    found: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()
    for control in controls:
        handlers: List[Tuple[str, str]] = []
        for class_name in control["classes"]:
            body = _handler_for_class(class_name, scripts)
            if body:
                handlers.append((class_name, body))
        diagnostic = {
            "year": control["year"],
            "classes": control["classes"],
            "data_keys": sorted(control["data"]),
            "matched_handler_classes": [name for name, _ in handlers],
            "candidate_targets": [],
        }
        diagnostics.append(diagnostic)
        for class_name, body in handlers:
            targets = reconstruct_data_targets(page_url, control["data"], body)
            diagnostic["candidate_targets"].extend(targets)
            for target in targets:
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                ok, final_url, content_type = scripted._verify_pdf(http, target, page_url)
                if not ok:
                    continue
                if not strict.strong_report_semantics(control["context"], final_url, page_url):
                    continue
                found.append({
                    "year": control["year"],
                    "label": control["context"][:200],
                    "url": final_url,
                    "source_locator": page_url,
                    "score": 110,
                    "content_type": content_type,
                    "download_contract": "VERIFIED_DATA_ATTRIBUTE_JS_HANDLER",
                    "handler_class": class_name,
                })
                break
            if any(item["year"] == control["year"] for item in found):
                break
    return found, diagnostics


def _report_pages(audit: Dict[str, Any]) -> List[str]:
    pages: List[str] = []
    corporate = ((audit.get("stages") or {}).get("corporate_documents") or {})
    pages.extend(corporate.get("report_index_pages") or [])
    navigation = ((audit.get("stages") or {}).get("scripted_report_navigation_recovery") or {})
    pages.extend(navigation.get("visited_pages") or [])
    generic = ((audit.get("stages") or {}).get("generic_js_report_recovery") or {})
    pages.extend(generic.get("visited_pages") or [])
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
        candidates, page_diagnostics = candidates_from_data_attr_page(
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
            "notes": "Annual-report DOM semantics + same-page data-attribute click-handler reconstruction + streamed PDF byte verification.",
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
    audit.setdefault("stages", {})["data_attr_report_recovery"] = {
        "visited_pages": _dedupe(visited),
        "recovered_years": sorted({int(c["year"]) for c in recovered}),
        "recovered_candidate_count": len(recovered),
        "control_diagnostics": diagnostics[:100],
    }
    audit.setdefault("http_attempts", []).extend(http.audit)
    return documents
