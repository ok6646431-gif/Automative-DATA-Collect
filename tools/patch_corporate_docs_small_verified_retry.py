from pathlib import Path

path=Path('collectors/corporate_docs_collect.py')
text=path.read_text(encoding='utf-8')
old='''                if expected_total >= SLOW_RETRY_MIN_DECLARED_BYTES and not_html and (not expected_ext or expected_ext != "pdf" or "pdf" in response_ctype):\n                    credible_document_response = True\n'''
new='''                expected_type_ok = (not expected_ext or expected_ext != "pdf" or "pdf" in response_ctype)\n                small_verified_document = bool(\n                    expected_total\n                    and expected_ext in {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx"}\n                )\n                if not_html and expected_type_ok and (\n                    expected_total >= SLOW_RETRY_MIN_DECLARED_BYTES or small_verified_document\n                ):\n                    credible_document_response = True\n'''
if new in text:
    print('Small verified-document retry patch already present')
elif old in text:
    path.write_text(text.replace(old,new,1),encoding='utf-8')
    print('Patched small verified-document retry handling')
else:
    raise SystemExit('Expected retry marker not found')
