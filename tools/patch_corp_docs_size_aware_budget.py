from pathlib import Path

p = Path('collectors/corporate_docs_collect.py')
text = p.read_text(encoding='utf-8')

constant_marker = 'SLOW_DOCUMENT_OVERHEAD_SECONDS = 60.0\nMAX_SLOW_DOCUMENT_WALL_SECONDS = 1200.0\n'
constant_replacement = 'SLOW_DOCUMENT_OVERHEAD_SECONDS = 60.0\nSLOW_RETRY_MIN_DECLARED_BYTES = 8 * 1024 * 1024\nMAX_SLOW_DOCUMENT_WALL_SECONDS = 1200.0\n'
if 'SLOW_RETRY_MIN_DECLARED_BYTES' not in text:
    assert constant_marker in text, 'slow retry constants not found'
    text = text.replace(constant_marker, constant_replacement, 1)

old = 'if expected_total and not_html and (not expected_ext or expected_ext != "pdf" or "pdf" in response_ctype):'
new = 'if expected_total >= SLOW_RETRY_MIN_DECLARED_BYTES and not_html and (not expected_ext or expected_ext != "pdf" or "pdf" in response_ctype):'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise AssertionError('credible document response condition not found')

p.write_text(text, encoding='utf-8')
print('Slow retry policy now requires either real byte progress or a credible large document response.')
