"""Repair the one-time guarded patch anchor and invoke source/coverage QA."""
import argparse
import subprocess
import sys
from pathlib import Path

p = Path(__file__).with_name('hanwha_quality_remediation.py')
s = p.read_text(encoding='utf-8')
lines = s.splitlines(keepends=True)
found = [i for i, line in enumerate(lines) if 'replace_once(collector,' in line and 'source_detail_identity(txt)' in line]
assert len(found) == 1, f'expected exactly one detail identity patch anchor, got {found}'
lines[found[0]] = '''    replace_once(collector, '"search_year":y,"bplcId":bid,"bplcNm":"","locplcAdres":"",', '"search_year":y,"bplcId":bid,**source_detail_identity(txt),')\n'''
p.write_text(''.join(lines),encoding='utf-8')

ap=argparse.ArgumentParser()
ap.add_argument('--test-source-root',required=True)
a=ap.parse_args()
subprocess.run([sys.executable,str(p),'--apply','--test-source-root',a.test_source_root],check=True)
