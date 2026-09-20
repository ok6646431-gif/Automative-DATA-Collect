"""One-shot, fail-closed remediation for source-native ICIS and annual report QA.

Invoked by the temporary Hanwha QA workflow. Every edit asserts its input contract;
unknown upstream changes stop the patch rather than producing an unreviewed mutation.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise AssertionError(f'{path}: expected one patch anchor, got {text.count(old)}: {old[:100]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def patch():
    collector = ROOT / 'collectors/chem_stats_collect.py'
    text = collector.read_text(encoding='utf-8')
    begin = text.index('def substantive_detail(html,bid):')
    end = text.index('\ndef write_jsonl(path,rows):', begin)
    before = text[begin:end]
    if 'ICIS returns the same page shell' not in before or 'for table in soup.find_all("table")[2:]:' not in before:
        raise AssertionError('collector substantive_detail contract changed')
    after = '''def substantive_detail(html,bid):
    """An ICIS shell/empty-product row is not survey data, even at HTTP 200."""
    if str(bid) not in html:
        return False,0
    soup=BeautifulSoup(html,"html.parser"); tables=soup.find_all("table"); count=0
    # First two tables contain facility metadata, not disclosed products/substances.
    for table in tables[2:]:
        for tr in table.find_all("tr"):
            tds=tr.find_all("td")
            if not tds: continue
            cells=[td.get_text(" ",strip=True) for td in tds]
            substantive=" ".join(cells).strip()
            normalized=re.sub(r"[\\s\\.。]+", "", substantive)
            # The source serves these placeholders as ordinary <td> cells.
            if not normalized or normalized in {"제품이없습니다", "물질이없습니다", "해당사항없음", "자료가없습니다", "정보가없습니다"}:
                continue
            if not re.search(r"[0-9A-Za-z가-힣]", substantive):
                continue
            count+=1
    return count>0,count


def source_detail_identity(html):
    """Preserve year-native legal/facility names separately from a newer ID anchor."""
    soup=BeautifulSoup(html,"html.parser")
    tables=soup.find_all("table")
    result={"bplcNm":"", "locplcAdres":""}
    if not tables: return result
    labels={"업체명":"bplcNm", "소재지":"locplcAdres"}
    for tr in tables[0].find_all("tr"):
        parts=tr.find_all(["th","td"],recursive=False)
        for idx,cell in enumerate(parts[:-1]):
            label=re.sub(r"\\s+","",cell.get_text(" ",strip=True))
            if cell.name=="th" and label in labels and parts[idx+1].name=="td":
                result[labels[label]]=parts[idx+1].get_text(" ",strip=True)
    return result

'''
    text = text[:begin] + after + text[end:]
    collector.write_text(text, encoding='utf-8')
    replace_once(collector, '"search_year":y,"bplcId":bid,"bplcNm":"","locplcAdres":"",', '"search_year":y,"bplcId":bid,**source_detail_identity(txt),')
    # Do not expose unvalidated discovery candidates to identity/scope builders.
    path = collector
    text = path.read_text(encoding='utf-8')
    a = text.index('        rows=list(dedup.values())\n')
    b = text.index('        write_jsonl(out/"excluded_rows.jsonl",excluded_rows)', a)
    old = text[a:b]
    if 'write_jsonl(out/"discovery.jsonl",rows)' not in old:
        raise AssertionError('collector discovery write contract changed')
    text=text[:a] + '        rows=list(dedup.values())\n' + text[b:]
    text=text.replace('        detail_ok=0; detail_fail=0; table_rows=[]\n', '        detail_ok=0; detail_fail=0; table_rows=[]; valid_pairs=set()\n', 1)
    text=text.replace('                    if valid: detail_ok+=1; table_rows.extend(generic_tables(txt,y,bid))\n', '                    if valid:\n                        detail_ok+=1; valid_pairs.add((y,bid)); table_rows.extend(generic_tables(txt,y,bid))\n                        native=source_detail_identity(txt)\n                        if native["bplcNm"]: source_row["bplcNm"]=native["bplcNm"]\n                        if native["locplcAdres"]: source_row["locplcAdres"]=native["locplcAdres"]\n', 1)
    marker='        write_jsonl(out/"detail_table_rows.jsonl",table_rows)\n'
    if text.count(marker)!=1: raise AssertionError('detail export marker changed')
    text=text.replace(marker, '''        accepted=[r for r in rows if (int(r["search_year"]), str(field_ci(r,"bplcid",None) or r.get("bplcId") or "")) in valid_pairs]
        rejected=[r for r in rows if (int(r["search_year"]), str(field_ci(r,"bplcid",None) or r.get("bplcId") or "")) not in valid_pairs]
        write_jsonl(out/"invalid_detail_rows.jsonl",rejected)
        if accepted:
            keys=sorted({k for r in accepted for k in r})
            with (out/"discovery.csv").open("w",newline="",encoding="utf-8-sig") as f:
                w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader(); w.writerows(accepted)
            write_jsonl(out/"discovery.jsonl",accepted)
        else:
            (out/"discovery.csv").unlink(missing_ok=True)
            write_jsonl(out/"discovery.jsonl",[])
        rows=accepted
''' + marker,1)
    if '"status":"DATA_FOUND" if rows else "NO_MATCH"' not in text:
        raise AssertionError('collector status contract changed')
    path.write_text(text,encoding='utf-8')

    archive = ROOT / 'orchestrator/archive_zip_dedup.py'
    old = '''    paths=[p for p in sorted(folder.rglob('*')) if p.is_file()] if folder.exists() else []
    coverage=evaluate_sustainability_coverage(profile,docs,paths)
'''
    new = '''    # Only a verified, downloaded official annual report can satisfy annual coverage.
    # ENV-INFO attachments (e.g. an ESG rating brief) may be stored in the same
    # user folder but must not masquerade as an official annual report.
    official={}
    for row in docs:
        if str(row.get('document_type') or '').upper()!='SUSTAINABILITY_REPORT': continue
        if str(row.get('collection_status') or '').upper()!='DOWNLOADED': continue
        if str(row.get('verification_status') or '').upper() not in STRONG_VERIFICATION: continue
        year=_gap_year(row.get('report_year'))
        src=package_root/str(row.get('stored_path') or '')
        if year is None or not src.is_file(): continue
        official.setdefault(year,[]).append((src.suffix.lower(),sha256(src)))
    paths=[]
    for p in sorted(folder.rglob('*')) if folder.exists() else []:
        if not p.is_file() or p.suffix.lower()!='.pdf': continue
        year=_gap_year(p.name)
        if year not in official: continue
        digest=sha256(p)
        matches=any(digest==source_hash for _,source_hash in official[year])
        rendered=any(ext in {'.html','.htm'} for ext,_ in official[year]) and re.search(r'_지속가능경영보고서_'+str(year)+r'\\.pdf$',p.name)
        if matches or rendered: paths.append(p)
    coverage=evaluate_sustainability_coverage(profile,docs,paths)
'''
    replace_once(archive,old,new)
    old2='''    coverage['resolved_without_file_years']=resolved_in_target
    coverage['missing_target_years']=missing
'''
    new2='''    overlap=sorted(delivered & set(resolved_in_target))
    coverage['resolved_without_file_years']=resolved_in_target
    coverage['conflicting_delivered_and_unpublished_years']=overlap
    coverage['missing_target_years']=missing
'''
    replace_once(archive,old2,new2)
    replace_once(archive,"coverage['coverage_sufficient']=not missing\n        coverage['state']='FILE_COVERAGE_COMPLETE' if not missing else 'FILE_COVERAGE_PARTIAL'", "coverage['coverage_sufficient']=not missing and not overlap\n        coverage['state']='FILE_COVERAGE_COMPLETE' if not missing and not overlap else 'FILE_COVERAGE_PARTIAL'")

    # ESG ratings/evaluation documents remain visible but are not annual reports.
    builder=ROOT/'orchestrator/archive_builder.py'
    replace_once(builder, "            folder=user/'04_지속가능경영보고서'\n        elif category=='CHEMICAL_MANAGEMENT':", "            folder=(user/'06_회사환경정책'/'기타_공식자료'/'ENVINFO_평가자료' if 'ESG평가' in original else user/'04_지속가능경영보고서')\n        elif category=='CHEMICAL_MANAGEMENT':")
    print('PATCH_APPLIED: collector substantive data, native identity, annual-document coverage, ESG reference routing')


def test(source_root):
    sys.path.insert(0,str(ROOT/'collectors'))
    sys.path.insert(0,str(ROOT/'orchestrator'))
    from chem_stats_collect import substantive_detail,source_detail_identity
    import archive_zip_dedup
    source_root=Path(source_root)
    bad=['ABC643N','ACB366N','ACC920N']
    for bid in bad:
        p=source_root/'CHEM_STATS'/'raw_detail'/f'2020_{bid}.html'
        assert p.is_file(), p
        valid,count=substantive_detail(p.read_text(encoding='utf-8'),bid)
        assert not valid and count==0, (bid,count)
    good=source_root/'CHEM_STATS'/'raw_detail'/'2020_AAR874N.html'
    assert good.is_file(),good
    assert substantive_detail(good.read_text(encoding='utf-8'),'AAR874N')[0]
    assert source_detail_identity(good.read_text(encoding='utf-8'))['bplcNm']
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); archive=root/'Human_Archive'/'테스트_환경자료'
        folder=archive/'01_사용자자료'/'04_지속가능경영보고서'; folder.mkdir(parents=True)
        raw=root/'output'/'CORP_DOCS'/'raw_documents'; raw.mkdir(parents=True)
        official=b'%PDF-1.4 example annual report %%EOF'
        (raw/'2021.pdf').write_bytes(official)
        (folder/'테스트_지속가능경영보고서_2021.pdf').write_bytes(official)
        (folder/'ENVINFO공개연도_2020_ESG평가 기본보고서(2020).pdf').write_bytes(b'%PDF-1.4 ESG evaluation %%EOF')
        docs=root/'output'/'CORP_DOCS'; docs.mkdir(parents=True,exist_ok=True)
        with (docs/'document_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['document_type','collection_status','verification_status','report_year','stored_path'])
            writer.writeheader(); writer.writerow({'document_type':'SUSTAINABILITY_REPORT','collection_status':'DOWNLOADED','verification_status':'SOURCE_VERIFIED','report_year':'2021','stored_path':'output/CORP_DOCS/raw_documents/2021.pdf'})
        (docs/'discovery_gaps.json').write_text(json.dumps([{'document_type':'SUSTAINABILITY_REPORT','verification_status':'VERIFIED','status':'NOT_PUBLISHED','report_year':2020,'blocking':False}]),encoding='utf-8')
        (root/'Company_Profile.json').write_text(json.dumps({'minimum_history_years':1,'requested_history_window':{'start_year':2020,'end_year':2021}}),encoding='utf-8')
        result=archive_zip_dedup._apply_sustainability_coverage(root,archive,{'acceptance_checks':{'envinfo_pdf_complete':True}})['sustainability_coverage']
        assert result['delivered_report_years']==[2021],result
        assert result['resolved_without_file_years']==[2020],result
        assert result['coverage_sufficient'],result
    print('TEST_PASS: 3 empty ICIS pages rejected, populated page accepted, report coverage excludes ESG evaluation')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--test-source-root')
    args=ap.parse_args()
    if args.apply: patch()
    if args.test_source_root: test(args.test_source_root)
