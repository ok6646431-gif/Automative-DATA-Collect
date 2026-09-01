from pathlib import Path

PATH = Path('collectors/corporate_docs_collect.py')
text = PATH.read_text(encoding='utf-8')

old = '''    credible_document_response = False\n    slow_mode = False\n    failures = 0\n    expected_ext = str(doc.get("expected_extension") or "").lower().lstrip(".")\n    segment_candidate = expected_ext in RANGE_SEGMENT_EXTENSIONS\n'''
new = '''    credible_document_response = False\n    slow_mode = False\n    failures = 0\n    # HTTP Range offsets are only safe when the bytes written locally represent\n    # the same transfer representation addressed by the origin. requests\n    # transparently decodes gzip/br responses, so an interrupted encoded response\n    # must restart from zero instead of resuming from the decoded byte count.\n    resume_representation_safe = True\n    expected_ext = str(doc.get("expected_extension") or "").lower().lstrip(".")\n    segment_candidate = expected_ext in RANGE_SEGMENT_EXTENSIONS\n'''
if old not in text:
    if new not in text:
        raise SystemExit('download_one state anchor not found')
else:
    text = text.replace(old, new, 1)

old = '''        request_headers = dict(headers)\n\n        range_requested = False\n        range_start = resume_offset\n'''
new = '''        request_headers = dict(headers)\n        # Exact artifact collection does not benefit from transparent HTTP\n        # compression. Asking for identity also keeps Content-Length and Range\n        # coordinates aligned with the bytes persisted to disk.\n        request_headers.setdefault("Accept-Encoding", "identity")\n        if resume_offset > 0 and not resume_representation_safe:\n            resume_offset = 0\n            target.unlink(missing_ok=True)\n\n        range_requested = False\n        range_start = resume_offset\n'''
if old not in text:
    if new not in text:
        raise SystemExit('request header anchor not found')
else:
    text = text.replace(old, new, 1)

old = '''                length = int(r.headers.get("Content-Length") or 0)\n                content_range = str(r.headers.get("Content-Range") or "")\n                range_match = re.match(r"bytes\\s+(\\d+)-(\\d+)/(\\d+|\\*)", content_range, re.I)\n'''
new = '''                length = int(r.headers.get("Content-Length") or 0)\n                content_encoding = str(r.headers.get("Content-Encoding") or "").strip().lower()\n                encoded_response = content_encoding not in {"", "identity"}\n                content_range = str(r.headers.get("Content-Range") or "")\n                range_match = re.match(r"bytes\\s+(\\d+)-(\\d+)/(\\d+|\\*)", content_range, re.I)\n'''
if old not in text:
    if new not in text:
        raise SystemExit('response header anchor not found')
else:
    text = text.replace(old, new, 1)

old = '''                if resume_offset > 0 and not range_accepted:\n                    # Origin ignored or inconsistently answered Range. Never append\n                    # a full 200 response to a partial file. Restart from zero.\n                    resume_offset = 0\n                    target.unlink(missing_ok=True)\n\n                expected_total = 0\n                if range_accepted and range_match and range_match.group(3) != "*":\n                    expected_total = int(range_match.group(3))\n                elif length and not range_accepted:\n                    expected_total = length\n                elif length and range_accepted:\n                    expected_total = resume_offset + length\n'''
new = '''                if encoded_response and not range_accepted:\n                    # requests.iter_content() yields decoded bytes. Content-Length\n                    # on an encoded response describes the wire representation, not\n                    # the decoded bytes saved to target, so neither exact-size\n                    # validation nor decoded-offset Range resume is safe.\n                    resume_representation_safe = False\n\n                if resume_offset > 0 and not range_accepted:\n                    # Origin ignored or inconsistently answered Range. Never append\n                    # a full 200 response to a partial file. Restart from zero.\n                    resume_offset = 0\n                    target.unlink(missing_ok=True)\n\n                expected_total = 0\n                if range_accepted and range_match and range_match.group(3) != "*":\n                    expected_total = int(range_match.group(3))\n                elif length and not range_accepted and not encoded_response:\n                    expected_total = length\n                elif length and range_accepted:\n                    expected_total = resume_offset + length\n'''
if old not in text:
    if new not in text:
        raise SystemExit('expected_total anchor not found')
else:
    text = text.replace(old, new, 1)

PATH.write_text(text, encoding='utf-8')
print('Patched corporate_docs_collect content-encoding handling')
