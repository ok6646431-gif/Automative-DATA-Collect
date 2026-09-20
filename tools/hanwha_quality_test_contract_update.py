"""Migrate two preexisting synthetic annual-report tests to evidence-backed fixtures.

The old tests counted any similarly named PDF as a delivered report. They must
now include verified official source rows AND matching source bytes.
"""
from pathlib import Path
root=Path(__file__).resolve().parents[1]

def once(file, old, new):
    p=root/file
    s=p.read_text(encoding='utf-8')
    assert s.count(old)==1, (file,old,s.count(old))
    p.write_text(s.replace(old,new,1),encoding='utf-8')

file='tests/test_archive_zip_dedup.py'
once(file,"            rows=[]\n            for year in [2022,2023,2024,2025]:\n                (reports/f'기업_지속가능경영보고서_{year}.pdf').write_bytes(b'%PDF-test')\n", "            rows=[]\n            official=docs/'raw_documents'; official.mkdir()\n            for year in [2022,2023,2024,2025]:\n                payload=b'%PDF-test'\n                (reports/f'기업_지속가능경영보고서_{year}.pdf').write_bytes(payload)\n                (official/f'{year}.pdf').write_bytes(payload)\n")
once(file,"                    'verification_status':'VERIFIED','collection_status':'DOWNLOADED',\n", "                    'verification_status':'VERIFIED','collection_status':'DOWNLOADED',\n                    'stored_path':f'output/CORP_DOCS/raw_documents/{year}.pdf',\n")
once(file,"fieldnames=['document_type','title','report_year','verification_status','collection_status']", "fieldnames=['document_type','title','report_year','verification_status','collection_status','stored_path']")
file='tests/test_scope_consistency_final.py'
once(file,"            reports.mkdir(parents=True)\n            for y in range(2020, 2027):\n                (reports / f\"report_{y}.pdf\").write_bytes(b\"%PDF-1.4\\n\" + b\"x\" * 300)\n", "            reports.mkdir(parents=True)\n            official = root / 'output' / 'CORP_DOCS' / 'raw_documents'\n            official.mkdir(parents=True)\n            for y in range(2020, 2027):\n                payload=b\"%PDF-1.4\\n\" + b\"x\" * 300\n                (reports / f\"report_{y}.pdf\").write_bytes(payload)\n                (official / f\"report_{y}.pdf\").write_bytes(payload)\n")
once(file,"                \"document_id,document_type,report_year,collection_status,stored_path\\n\"", "                \"document_id,document_type,report_year,collection_status,verification_status,stored_path\\n\"")
once(file,"                docs.append(f\"D{y},SUSTAINABILITY_REPORT,{y},DOWNLOADED,report_{y}.pdf\\n\")", "                docs.append(f\"D{y},SUSTAINABILITY_REPORT,{y},DOWNLOADED,VERIFIED,output/CORP_DOCS/raw_documents/report_{y}.pdf\\n\")")
once(file,"            docs_dir.mkdir(parents=True)\n", "            docs_dir.mkdir(parents=True,exist_ok=True)\n")
print('TEST_FIXTURES_UPDATED: official verified source required; no assertion weakened')
