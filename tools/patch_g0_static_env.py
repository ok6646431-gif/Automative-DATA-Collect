from pathlib import Path

CODE = Path('orchestrator/g0_generic_js_report_recovery.py')
TEST = Path('tests/test_g0_scripted_report_enrichment.py')

old = '''def _eval_concat(expr: str, env: Mapping[str, str]) -> str | None:
    out: List[str] = []
    for token in _split_concat(str(expr or "").strip().rstrip(";")):
        literal = _literal_arg(token)
        if literal is not None:
            out.append(literal); continue
        name = token.strip()
        if name in env:
            out.append(str(env[name])); continue
        encoded = re.fullmatch(r"(?:encodeURIComponent|encodeURI)\\s*\\(\\s*([A-Za-z_$][\\w$]*)\\s*\\)", name)
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
        r"(?:window\\.)?location(?:\\.href)?\\s*=\\s*(?P<expr>[^;\\n]{1,1200})",
        r"(?:window\\.)?open\\s*\\(\\s*(?P<expr>[^,;\\n]{1,1200})",
        r"(?:document\\.)?location\\.replace\\s*\\(\\s*(?P<expr>[^);\\n]{1,1200})",
        r"(?:var\\s+|let\\s+|const\\s+)?(?:url|action)\\s*[:=]\\s*(?P<expr>[^,;\\n]{1,1200})",
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
'''

new = '''def _env_options(env: Mapping[str, Any], name: str) -> List[str]:
    value = env.get(name)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return _dedupe(str(x) for x in value)
    return [str(value)]


def _eval_concat_values(expr: str, env: Mapping[str, Any], max_values: int = 24) -> List[str]:
    """Statically evaluate literal/parameter string concatenation to bounded values.

    The evaluator intentionally supports only quoted literals, already-resolved local
    identifiers and encodeURI/encodeURIComponent(identifier). It never executes JS.
    """
    values = [""]
    for token in _split_concat(str(expr or "").strip().rstrip(";")):
        literal = _literal_arg(token)
        if literal is not None:
            options = [literal]
        else:
            name = token.strip()
            options = _env_options(env, name)
            if not options:
                encoded = re.fullmatch(
                    r"(?:encodeURIComponent|encodeURI)\\s*\\(\\s*([A-Za-z_$][\\w$]*)\\s*\\)",
                    name,
                )
                if encoded:
                    options = [quote(v, safe="") for v in _env_options(env, encoded.group(1))]
            if not options:
                return []
        combined: List[str] = []
        for prefix in values:
            for option in options:
                combined.append(prefix + option)
                if len(combined) >= max_values:
                    break
            if len(combined) >= max_values:
                break
        values = _dedupe(combined)
        if not values:
            return []
    return values[:max_values]


def _eval_concat(expr: str, env: Mapping[str, Any]) -> str | None:
    values = _eval_concat_values(expr, env, max_values=1)
    return values[0] if values else None


def _static_local_env(body: str, params: Sequence[str], args: Sequence[str]) -> Dict[str, List[str]]:
    """Resolve bounded local string assignments from literals/parameters only.

    Multiple branch assignments are preserved as alternative values. Only declarations
    and += concatenations are recognized; arbitrary statements, calls and conditions are
    never evaluated.
    """
    env: Dict[str, List[str]] = {
        str(name): [str(value)] for name, value in zip(params, args)
    }
    declarations = list(re.finditer(
        r"(?:var|let|const)\\s+(?P<name>[A-Za-z_$][\\w$]*)\\s*=\\s*(?P<expr>[^;\\n]{1,1200})",
        body,
        re.I,
    ))
    appends = list(re.finditer(
        r"(?<![.\\w$])(?P<name>[A-Za-z_$][\\w$]*)\\s*\\+=\\s*(?P<expr>[^;\\n]{1,1200})",
        body,
        re.I,
    ))
    for _ in range(6):
        changed = False
        for match in declarations:
            values = _eval_concat_values(match.group("expr"), env)
            if not values:
                continue
            name = match.group("name")
            merged = _dedupe([*(env.get(name) or []), *values])[:24]
            if merged != (env.get(name) or []):
                env[name] = merged
                changed = True
        for match in appends:
            name = match.group("name")
            left = env.get(name) or []
            right = _eval_concat_values(match.group("expr"), env)
            if not left or not right:
                continue
            values = _dedupe(a + b for a in left for b in right)[:24]
            if values != left:
                env[name] = values
                changed = True
        if not changed:
            break
    return env


def reconstruct_targets(page_url: str, params: Sequence[str], args: Sequence[str], body: str) -> List[str]:
    if len(params) != len(args):
        return []
    env = _static_local_env(body, params, args)
    expressions: List[str] = []
    patterns = (
        r"(?:window\\.)?location(?:\\.href)?\\s*=\\s*(?P<expr>[^;\\n]{1,1200})",
        r"(?:window\\.)?open\\s*\\(\\s*(?P<expr>[^,;\\n]{1,1200})",
        r"(?:document\\.)?location\\.replace\\s*\\(\\s*(?P<expr>[^);\\n]{1,1200})",
        r"(?:var\\s+|let\\s+|const\\s+)?(?:url|uri|href|src|path|action|downloadUrl|fileUrl|pdfUrl)\\s*[:=]\\s*(?P<expr>[^,;\\n]{1,1200})",
    )
    for pattern in patterns:
        expressions.extend(m.group("expr") for m in re.finditer(pattern, body, re.I))

    # A literal function argument may itself be the declared report target. This is
    # still fail-closed because same-org and real PDF-byte verification occur later.
    expressions.extend(str(arg) for arg in args if URLISH_LITERAL_RE.search(str(arg)))

    targets: List[str] = []
    for expr in expressions:
        values = _eval_concat_values(expr, env)
        if not values:
            literal = str(expr or "").strip()
            values = [literal] if URLISH_LITERAL_RE.search(literal) else []
        for value in values:
            if not value or not URLISH_LITERAL_RE.search(value):
                continue
            target = urljoin(page_url, value)
            parsed = urlparse(target)
            if parsed.scheme in {"http", "https"} and base._same_org_host(target, page_url):
                targets.append(target)
    return _dedupe(targets)
'''

code = CODE.read_text(encoding='utf-8')
if old not in code:
    raise SystemExit('target reconstruct block not found; refusing unsafe patch')
CODE.write_text(code.replace(old, new), encoding='utf-8')

test = TEST.read_text(encoding='utf-8')
route_anchor = '''        if url.endswith("/files/report_2020_kor.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\ndirect-js",\n                content_type="application/pdf",\n            )\n'''
route_insert = route_anchor + '''        if url.endswith("/assets/file/report_2024_kor.pdf"):\n            return FakeResponse(\n                url,\n                content=b"%PDF-1.7\\nstatic-local-env",\n                content_type="application/pdf",\n            )\n'''
if route_anchor not in test:
    raise SystemExit('test HTTP anchor not found')
test = test.replace(route_anchor, route_insert, 1)

test_anchor = '''    def test_direct_window_open_literal_is_recovered_without_function_definition(self):\n'''
new_test = '''    def test_generic_js_resolves_intermediate_local_variables(self):\n        html = \'\'\'\n        <html><body>\n          <article class="annual-report">\n            <h3>2024 지속가능경영보고서</h3>\n            <a href="javascript:void(0)" onclick="mergeReport(\'2024\',\'kor\')">\n              KOR PDF 다운로드\n            </a>\n          </article>\n          <script>\n          function mergeReport(year, lang) {\n            var fileName = "report_" + year + "_" + lang + ".pdf";\n            var basePath = "/assets/file/";\n            var reportPath = basePath + fileName;\n            window.open(reportPath);\n          }\n          </script>\n        </body></html>\n        \'\'\'\n        found, diagnostics = candidates_from_generic_js_page(\n            FakeHttp(),\n            "https://official.example/esg/report/",\n            html,\n            2020,\n            2026,\n        )\n        self.assertEqual(len(found), 1)\n        self.assertEqual(found[0]["year"], 2024)\n        self.assertEqual(\n            found[0]["url"],\n            "https://official.example/assets/file/report_2024_kor.pdf",\n        )\n        self.assertTrue(diagnostics[0]["function_definition_found"])\n        self.assertIn(\n            "https://official.example/assets/file/report_2024_kor.pdf",\n            diagnostics[0]["candidate_targets"],\n        )\n\n'''
if test_anchor not in test:
    raise SystemExit('test insertion anchor not found')
TEST.write_text(test.replace(test_anchor, new_test + test_anchor, 1), encoding='utf-8')

print('patched', CODE, TEST)
