from pathlib import Path

path=Path('tests/test_corporate_docs_collect.py')
text=path.read_text(encoding='utf-8')
old='ticks=iter([0.0, 0.0, 121.0, 121.0, 121.0])'
new='ticks=iter([0.0, 0.0, 361.0, 361.0, 361.0, 361.0, 361.0])'
if new in text:
    print('Slow-drip budget test already updated')
elif old in text:
    path.write_text(text.replace(old,new,1),encoding='utf-8')
    print('Updated slow-drip budget test for bounded extended retry')
else:
    raise SystemExit('Expected slow-drip test marker not found')
