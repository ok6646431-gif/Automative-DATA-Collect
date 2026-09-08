from pathlib import Path

p=Path('orchestrator/bat_collector.py')
s=p.read_text(encoding='utf-8')

old="""            specs=_document_specs(entry)
            for spec in specs:
                part=str(spec.get('document_part') or '1'); volume_no=str(spec.get('volume_no') or part)
                docid='BAT_'+re.sub(r'[^0-9A-Za-z_]+','_',catalog_id)+(f'_P{part}' if len(specs)>1 else '')
                title=str(spec.get('title') or entry.get('title') or '')
                base={
                    'document_id':docid,'catalog_id':catalog_id,'catalog_family':family,'revision_id':revision_id,
                    'revision_generation':revision,'publication_year':publication_year,
                    'revision_status':'SUPERSEDED_ARCHIVE_ONLY' if archive_only else revision_status,
                    'preferred_for_matching':'false' if archive_only else 'true',
                    'document_part':part,'volume_no':volume_no,'document_type':'BAT_REFERENCE','title':title,
                    'report_year':publication_year,'source_url':'','source_locator':entry.get('official_source_locator',''),
"""
new="""            specs=_document_specs(entry)
            for spec in specs:
                part=str(spec.get('document_part') or '1'); volume_no=str(spec.get('volume_no') or part)
                spec_publication_year=str(spec.get('publication_year') or entry.get('publication_year') or entry.get('effective_from') or '')[:4]
                docid='BAT_'+re.sub(r'[^0-9A-Za-z_]+','_',catalog_id)+(f'_P{part}' if len(specs)>1 else '')
                title=str(spec.get('title') or entry.get('title') or '')
                base={
                    'document_id':docid,'catalog_id':catalog_id,'catalog_family':family,'revision_id':revision_id,
                    'revision_generation':revision,'publication_year':spec_publication_year,
                    'revision_status':'SUPERSEDED_ARCHIVE_ONLY' if archive_only else revision_status,
                    'preferred_for_matching':'false' if archive_only else 'true',
                    'document_part':part,'volume_no':volume_no,'document_type':'BAT_REFERENCE','title':title,
                    'report_year':spec_publication_year,'source_url':'','source_locator':entry.get('official_source_locator',''),
"""
if old not in s:
    raise SystemExit('multipart metadata block not found')
s=s.replace(old,new)

old="folder=out/'documents'/safe(family)/safe(f'{publication_year}_{revision or catalog_id}')"
if s.count(old)!=2:
    raise SystemExit(f'expected two folder year call sites, got {s.count(old)}')
s=s.replace(old,"folder=out/'documents'/safe(family)/safe(f'{spec_publication_year}_{revision or catalog_id}')")
p.write_text(s,encoding='utf-8')

t=Path('tests/test_bat_revision_collection.py')
q=t.read_text(encoding='utf-8')
old="""             'official_documents':[
                 {'document_part':'1','volume_no':'I','title':'다권 BAT 제1권','official_document_page':'https://ieps.nier.go.kr/web/board/5/11/'},
                 {'document_part':'2','volume_no':'II','title':'다권 BAT 제2권','official_document_page':'https://ieps.nier.go.kr/web/board/5/12/'},
             ]}
"""
new="""             'official_documents':[
                 {'document_part':'1','volume_no':'I','publication_year':2023,'title':'다권 BAT 제1권','official_document_page':'https://ieps.nier.go.kr/web/board/5/11/'},
                 {'document_part':'2','volume_no':'II','publication_year':2024,'title':'다권 BAT 제2권','official_document_page':'https://ieps.nier.go.kr/web/board/5/12/'},
             ]}
"""
if old not in q:
    raise SystemExit('multipart test documents block not found')
q=q.replace(old,new,1)
old="""            self.assertEqual({r['document_part'] for r in rows},{'1','2'})
            self.assertEqual({r['volume_no'] for r in rows},{'I','II'})
            self.assertEqual(status['current_downloaded'],2)
            self.assertNotEqual(rows[0]['stored_path'],rows[1]['stored_path'])
"""
new="""            self.assertEqual({r['document_part'] for r in rows},{'1','2'})
            self.assertEqual({r['volume_no'] for r in rows},{'I','II'})
            by_part={r['document_part']:r for r in rows}
            self.assertEqual(by_part['1']['publication_year'],'2023')
            self.assertEqual(by_part['1']['report_year'],'2023')
            self.assertIn('2023_II',by_part['1']['stored_path'])
            self.assertEqual(by_part['2']['publication_year'],'2024')
            self.assertEqual(by_part['2']['report_year'],'2024')
            self.assertIn('2024_II',by_part['2']['stored_path'])
            self.assertEqual(status['current_downloaded'],2)
            self.assertNotEqual(rows[0]['stored_path'],rows[1]['stored_path'])
"""
if old not in q:
    raise SystemExit('multipart test assertions block not found')
q=q.replace(old,new,1)
t.write_text(q,encoding='utf-8')
