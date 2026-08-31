from pathlib import Path

p=Path('tests/test_corporate_docs_collect.py')
text=p.read_text(encoding='utf-8')
old='''            self.assertEqual(session.get.call_args_list[1].kwargs["headers"]["Range"],f"bytes={cut}-")\n'''
new='''            self.assertEqual(session.get.call_args_list[1].kwargs["headers"]["Range"],f"bytes={cut}-{len(full)-1}")\n'''
assert old in text, 'legacy resume Range assertion not found'
p.write_text(text.replace(old,new,1),encoding='utf-8')
print('Updated resume regression to require a bounded Range request.')
