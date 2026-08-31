from pathlib import Path

p=Path('orchestrator/postprocess.py')
text=p.read_text(encoding='utf-8')
old='''        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue\n        if site.get("identity_status") != "CONFIRMED": continue\n'''
new='''        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue\n        # Discovery/profile schemas historically used VERIFIED for a site whose\n        # identity had already been source-verified, while this resolver originally\n        # accepted only CONFIRMED. Treat both as strong identity states only when the\n        # independent verification_state above is also strong.\n        if site.get("identity_status") not in {"CONFIRMED","VERIFIED","SOURCE_VERIFIED"}: continue\n'''
if old not in text:
    raise RuntimeError('postprocess identity-status snippet not found')
p.write_text(text.replace(old,new,1),encoding='utf-8')

t=Path('tests/test_postprocess.py')
txt=t.read_text(encoding='utf-8')
anchor='''    def test_ambiguous_verified_profile_address_does_not_auto_confirm(self):\n'''
test='''    def test_verified_identity_status_profile_address_confirms_single_source(self):\n        profile={**PROFILE,"site_candidates":[{\n            "candidate_id":"test-daesan",\n            "site_name_raw":"대산공장",\n            "address_raw":"충청남도 서산시 대산읍 독곶1로 54",\n            "identity_status":"VERIFIED",\n            "verification_state":"VERIFIED",\n        }]}\n        cs=[\n          {"source_key":"CHEM_STATS","source_site_id":"A","source_site_name_raw":"테스트화학","source_address_raw":"충남 서산시 대산읍 독곶1로 54","years":[2024]},\n        ]\n        _,sites,ids,vals=resolve_identity(cs,profile)\n        self.assertEqual(sum(x["identity_status"]=="CONFIRMED" for x in sites),1)\n        self.assertEqual(ids[0]["match_status"],"CONFIRMED")\n        self.assertEqual(ids[0]["match_basis"],"OFFICIAL_SITE_EXACT_ADDRESS")\n        self.assertEqual(vals,[])\n\n'''
if anchor not in txt:
    raise RuntimeError('test insertion anchor not found')
t.write_text(txt.replace(anchor,test+anchor,1),encoding='utf-8')
print('patched verified identity status handling and regression test')
