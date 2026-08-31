from pathlib import Path

p=Path('collectors/corporate_docs_collect.py')
text=p.read_text(encoding='utf-8')

old='''TRANSFER_ATTEMPTS = 4\nPREFLIGHT_TIMEOUT = (8, 15)\n'''
new='''TRANSFER_ATTEMPTS = 4\nRANGE_SEGMENT_BYTES = 1024 * 1024\nRANGE_SEGMENT_EXTENSIONS = {"pdf"}\nPREFLIGHT_TIMEOUT = (8, 15)\n'''
assert old in text, 'transfer constants block not found'
text=text.replace(old,new,1)

start=text.index('def download_one(session, doc, target, total_bytes):')
end=text.index('\n\ndef source_candidates(doc):', start)
new_func=r'''def download_one(session, doc, target, total_bytes):
    """Download one verified document with bounded retries and safe Range resume.

    For PDF origins that honor HTTP Range, start with a bounded segment and keep
    appending verified contiguous segments. This prevents one very slow connection
    from having to carry an entire large document. Origins that ignore Range keep
    the ordinary full-response path. A full 200 response is never appended to a
    partial file.
    """
    url = str(doc.get("source_url") or "")
    headers = preflight(session, doc, url)
    last_exc = None
    started = time.monotonic()
    deadline = started + BASE_DOCUMENT_WALL_SECONDS
    active_budget = BASE_DOCUMENT_WALL_SECONDS
    resume_offset = target.stat().st_size if target.exists() else 0
    known_total = 0
    credible_document_response = False
    slow_mode = False
    failures = 0
    expected_ext = str(doc.get("expected_extension") or "").lower().lstrip(".")
    segment_candidate = expected_ext in RANGE_SEGMENT_EXTENSIONS

    while True:
        if slow_mode:
            active_budget = max(active_budget, slow_wall_budget_for_length(known_total or resume_offset))
            deadline = max(deadline, started + active_budget)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last_exc = TimeoutError(f"document wall-clock budget exceeded ({active_budget:.0f}s)")
            break
        connect_timeout = max(1.0, min(float(DOWNLOAD_TIMEOUT[0]), remaining))
        read_ceiling = SLOW_RETRY_READ_TIMEOUT_SECONDS if slow_mode else float(DOWNLOAD_TIMEOUT[1])
        read_timeout = max(1.0, min(read_ceiling, remaining))
        request_headers = dict(headers)

        range_requested = False
        range_start = resume_offset
        range_end = None
        if segment_candidate:
            range_requested = True
            if known_total:
                range_end = min(known_total - 1, range_start + RANGE_SEGMENT_BYTES - 1)
            else:
                range_end = range_start + RANGE_SEGMENT_BYTES - 1
            request_headers["Range"] = f"bytes={range_start}-{range_end}"
        elif resume_offset > 0:
            range_requested = True
            request_headers["Range"] = f"bytes={resume_offset}-"

        try:
            with session.get(
                url, stream=True, timeout=(connect_timeout, read_timeout),
                allow_redirects=True, headers=request_headers
            ) as r:
                r.raise_for_status()
                status_code = int(getattr(r, "status_code", 200) or 200)
                length = int(r.headers.get("Content-Length") or 0)
                content_range = str(r.headers.get("Content-Range") or "")
                range_match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range, re.I)
                range_accepted = bool(
                    range_requested and status_code == 206 and range_match
                    and int(range_match.group(1)) == range_start
                )

                if resume_offset > 0 and not range_accepted:
                    # Origin ignored or inconsistently answered Range. Never append
                    # a full 200 response to a partial file. Restart from zero.
                    resume_offset = 0
                    target.unlink(missing_ok=True)

                expected_total = 0
                if range_accepted and range_match and range_match.group(3) != "*":
                    expected_total = int(range_match.group(3))
                elif length and not range_accepted:
                    expected_total = length
                elif length and range_accepted:
                    expected_total = resume_offset + length

                if expected_total and expected_total > MAX_FILE_BYTES:
                    raise ValueError(f"declared file size exceeds {MAX_FILE_BYTES} bytes")
                known_total = max(known_total, expected_total)
                budget_basis = expected_total or max(resume_offset + length, resume_offset)
                active_budget = wall_budget_for_length(budget_basis)
                if slow_mode:
                    active_budget = max(active_budget, slow_wall_budget_for_length(known_total or budget_basis))
                deadline = max(deadline, started + active_budget)

                response_ctype = str(r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                not_html = response_ctype not in {"text/html", "application/xhtml+xml"}
                if expected_total >= SLOW_RETRY_MIN_DECLARED_BYTES and not_html and (not expected_ext or expected_ext != "pdf" or "pdf" in response_ctype):
                    credible_document_response = True

                mode = "ab" if range_accepted else "wb"
                count = resume_offset if range_accepted else 0
                with target.open(mode) as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if time.monotonic() > deadline:
                            raise TimeoutError(f"document wall-clock budget exceeded ({active_budget:.0f}s)")
                        if not chunk:
                            continue
                        count += len(chunk)
                        if not expected_total:
                            active_budget = wall_budget_for_length(count)
                            if slow_mode:
                                active_budget = max(active_budget, slow_wall_budget_for_length(count))
                            deadline = max(deadline, started + active_budget)
                        if count > MAX_FILE_BYTES or total_bytes + count > MAX_TOTAL_BYTES:
                            raise ValueError("document collection size safety limit exceeded")
                        f.write(chunk)

                if count == 0:
                    raise ValueError("zero-byte document response")

                if range_accepted and range_match:
                    response_end = int(range_match.group(2)) + 1
                    if count != response_end:
                        raise requests.exceptions.ConnectionError(
                            f"incomplete ranged response: received={count}; expected_end={response_end}"
                        )
                    if expected_total and count < expected_total:
                        # Successful bounded segment. Continue from the exact next
                        # byte without consuming a failure/retry allowance.
                        resume_offset = count
                        failures = 0
                        continue

                if expected_total and count != expected_total:
                    raise requests.exceptions.ConnectionError(
                        f"incomplete document response: received={count}; expected={expected_total}"
                    )
                ctype = str(r.headers.get("Content-Type") or "").split(";")[0]
                validate_payload(doc.get("expected_extension"), ctype, target)
                return r, count, ctype
        except Exception as exc:
            last_exc = exc
            retryable = isinstance(exc, (requests.exceptions.RequestException, TimeoutError))
            if not retryable:
                target.unlink(missing_ok=True)
                break
            failures += 1
            resume_offset = target.stat().st_size if target.exists() else 0
            if resume_offset > 0 or credible_document_response:
                slow_mode = True
                active_budget = max(active_budget, slow_wall_budget_for_length(known_total or resume_offset))
                deadline = max(deadline, started + active_budget)
            if failures < TRANSFER_ATTEMPTS and time.monotonic() < deadline:
                time.sleep(min(0.5 * failures, max(0.0, deadline - time.monotonic())))
                continue
            break
    raise last_exc
'''
text=text[:start]+new_func+text[end:]
p.write_text(text,encoding='utf-8')
print('Patched corporate document collector with bounded Range segmentation.')
