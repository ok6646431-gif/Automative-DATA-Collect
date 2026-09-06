from pathlib import Path


def replace_once(path, old, new):
    p=Path(path)
    text=p.read_text(encoding='utf-8')
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f'patch target not found in {path}: {old[:120]!r}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')
    return True


# Archive user-layer filtering: preserve source raw, exclude only the human-facing copy.
p='orchestrator/archive_builder.py'
replace_once(
    p,
    'from requested_scope import company_terms as _company_terms, source_id_scope as _resolved_source_id_scope\n',
    'from requested_scope import company_terms as _company_terms, source_id_scope as _resolved_source_id_scope\nfrom cross_entity_attachment_scope import match_envinfo_attachment\n',
)
replace_once(
    p,
    "    root=Path(package_root); env=root/'output'/'ENVINFO'; user=Path(archive_root)/USER_ROOT/'03_환경정보공개시스템'; created=[]; failures=[]\n    profile=read_json(root/'Company_Profile.json',{}) or {}; tokens=target_site_tokens(profile)\n",
    "    root=Path(package_root); env=root/'output'/'ENVINFO'; user=Path(archive_root)/USER_ROOT/'03_환경정보공개시스템'; created=[]; failures=[]; exclusions=[]\n    profile=read_json(root/'Company_Profile.json',{}) or {}; tokens=target_site_tokens(profile)\n    requested_scope=read_json(root/'Requested_Scope.json',{}) or {}\n",
)
replace_once(
    p,
    "        comp=str(att.get('compId') or '')\n        if comp not in scope['ENVINFO'] or att.get('collection_status')!='DOWNLOADED': continue\n        src=root/str(att.get('stored_path') or '')\n",
    "        comp=str(att.get('compId') or '')\n        if comp not in scope['ENVINFO'] or att.get('collection_status')!='DOWNLOADED': continue\n        decision=match_envinfo_attachment(att,requested_scope)\n        if decision:\n            exclusions.append({\n                'source_key':'ENVINFO',\n                'parent_source_site_id':comp,\n                'parent_source_site_name':str(att.get('compNm') or labels.get(('ENVINFO',comp),comp)),\n                'year':str(att.get('year') or ''),\n                'file_id':str(att.get('file_id') or ''),\n                'original_filename':str(att.get('original_filename') or ''),\n                'sha256':str(att.get('sha256') or ''),\n                **decision,\n            })\n            continue\n        src=root/str(att.get('stored_path') or '')\n",
)
replace_once(p, '    return created,failures\n\n\ndef promote_envinfo_references', '    return created,failures,exclusions\n\n\ndef promote_envinfo_references')
replace_once(
    p,
    "    root=Path(package_root); env=root/'output'/'ENVINFO'; user=Path(archive_root)/USER_ROOT; created=[]\n    for att in read_csv(env/'attachment_index.csv'):\n",
    "    root=Path(package_root); env=root/'output'/'ENVINFO'; user=Path(archive_root)/USER_ROOT; created=[]\n    requested_scope=read_json(root/'Requested_Scope.json',{}) or {}\n    for att in read_csv(env/'attachment_index.csv'):\n",
)
replace_once(
    p,
    "        comp=str(att.get('compId') or '')\n        if comp not in scope['ENVINFO'] or att.get('collection_status')!='DOWNLOADED': continue\n        src=root/str(att.get('stored_path') or '')\n        if not src.exists(): continue\n        section_id=str(att.get('section_id') or '').strip().lower()\n",
    "        comp=str(att.get('compId') or '')\n        if comp not in scope['ENVINFO'] or att.get('collection_status')!='DOWNLOADED': continue\n        if match_envinfo_attachment(att,requested_scope): continue\n        src=root/str(att.get('stored_path') or '')\n        if not src.exists(): continue\n        section_id=str(att.get('section_id') or '').strip().lower()\n",
)
replace_once(
    p,
    "    env_created,env_failures=build_envinfo_user(package_root,archive_root,scope,labels)\n",
    "    env_created,env_failures,env_cross_entity=build_envinfo_user(package_root,archive_root,scope,labels)\n",
)
replace_once(
    p,
    "    user_files=write_user_indexes(package_root,archive_root,document_rows,env_failures)\n    exposed_docs=docs_created+promoted\n",
    "    user_files=write_user_indexes(package_root,archive_root,document_rows,env_failures)\n    cross_entity_index=''\n    if env_cross_entity:\n        cross_entity_index='00_자료목록/ENVINFO_범위외_첨부자료.csv'\n        write_csv(archive_root/cross_entity_index,env_cross_entity,[\n            'source_key','parent_source_site_id','parent_source_site_name','year','file_id',\n            'original_filename','sha256','decision','matched_surface','matched_excluded_entity',\n            'matched_excluded_source_id','matched_exclusion_reason','normalized_match'\n        ])\n    exposed_docs=docs_created+promoted\n",
)
replace_once(
    p,
    "'envinfo_promoted_references':len(promoted),'envinfo_pdf_failures':env_failures,'principle':",
    "'envinfo_promoted_references':len(promoted),'envinfo_pdf_failures':env_failures,'envinfo_cross_entity_attachment_exclusions':len(env_cross_entity),'envinfo_cross_entity_attachment_exclusion_file':cross_entity_index,'principle':",
)

# Coverage is the authoritative annual-report completeness contract once available.
p='orchestrator/scope_quality.py'
old='''    guideline = bool(checks.get("guideline_reference_present"))\n    blocking = {\n        key: bool(value)\n        for key, value in checks.items()\n        if key != "guideline_reference_present"\n    }\n    blocking["collection_completeness_complete"] = collection.get("status") == "COMPLETE"\n    study = {"guideline_reference_present": guideline}\n\n    result["acceptance_checks"] = {**blocking, **study}\n    result["blocking_acceptance_checks"] = blocking\n    result["study_enrichment_checks"] = study\n'''
new='''    guideline = bool(checks.get("guideline_reference_present"))\n    coverage_contract_present = "sustainability_coverage_sufficient" in checks\n    legacy_observability = {}\n    blocking = {}\n    for key, value in checks.items():\n        if key == "guideline_reference_present":\n            continue\n        if key == "sustainability_minimum_5" and coverage_contract_present:\n            # Legacy physical-file heuristic. Once annual coverage has been explicitly\n            # resolved, a verified NOT_PUBLISHED/NO_PUBLIC_DOCUMENT year needs no fake\n            # fifth file and must not make the archive incomplete.\n            legacy_observability[key] = bool(value)\n            continue\n        blocking[key] = bool(value)\n    blocking["collection_completeness_complete"] = collection.get("status") == "COMPLETE"\n    study = {"guideline_reference_present": guideline}\n\n    result["acceptance_checks"] = {**blocking, **legacy_observability, **study}\n    result["blocking_acceptance_checks"] = blocking\n    result["legacy_observability_checks"] = legacy_observability\n    result["study_enrichment_checks"] = study\n'''
replace_once(p,old,new)

print('cross-entity attachment scope patch applied')
