from pathlib import Path

TARGET = Path("orchestrator/postprocess.py")
TEST = Path("tests/test_admin_region_address_continuity.py")

text = TARGET.read_text(encoding="utf-8")

old = 'FACILITY_WORDS=["사업장","공장","캠퍼스","연구원","기술연구원"]\n'
new = '''FACILITY_WORDS=["사업장","공장","캠퍼스","연구원","기술연구원"]\nTOP_LEVEL_REGION_RE=re.compile(\n    r"^(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\\s+"\n    r"|[가-힣]{2,24}(?:특별자치도|특별자치시|광역시|특별시|도)\\s+)"\n)\n'''
if old not in text:
    raise SystemExit("FACILITY_WORDS anchor not found")
text = text.replace(old, new, 1)

old = '''    s=re.sub(r"[\\s,._·ㆍ()\\[\\]{}\\-_/\\\\]","",s).lower()\n    return s\n\n\ndef embedded_facility_name_key(value, profile=None):\n'''
new = '''    s=re.sub(r"[\\s,._·ㆍ()\\[\\]{}\\-_/\\\\]","",s).lower()\n    return s\n\n\ndef normalize_address_locality(x, profile=None):\n    """Normalize the stable road-address portion below the top-level region.\n\n    This key is deliberately weaker than ``normalize_address`` and is never sufficient\n    by itself for identity resolution.  It exists to bridge verified physical sites\n    across top-level administrative reorganizations while preserving the raw address.\n    Downstream resolution may use it only when the official-site locality is unique and\n    at least two independent public sources corroborate the same locality key.\n    """\n    s=re.sub(r"\\s+"," ",str(x or "")).strip()\n    if not s: return ""\n    s=TOP_LEVEL_REGION_RE.sub("",s,count=1)\n    return normalize_address(s,profile)\n\n\ndef embedded_facility_name_key(value, profile=None):\n'''
if old not in text:
    raise SystemExit("normalize_address insertion anchor not found")
text = text.replace(old, new, 1)

old = '''    official_by_addr=defaultdict(list)\n    for site in profile.get("site_candidates",[]) or []:\n        if not isinstance(site,dict): continue\n        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue\n        # Discovery/profile schemas historically used VERIFIED for a site whose\n        # identity had already been source-verified, while this resolver originally\n        # accepted only CONFIRMED. Treat both as strong identity states only when the\n        # independent verification_state above is also strong.\n        if site.get("identity_status") not in {"CONFIRMED","VERIFIED","SOURCE_VERIFIED"}: continue\n        addr=normalize_address(site.get("address_raw"),profile)\n        if addr: official_by_addr[addr].append(site)\n    official_unique={addr:items[0] for addr,items in official_by_addr.items() if len(items)==1}\n\n    # Cross-source confirmation remains available for sites that do not have a\n    # unique verified Discovery address anchor.\n    by_pair=defaultdict(list); by_addr=defaultdict(list)\n    for c in candidates:\n        c["address_key"]=normalize_address(c.get("source_address_raw"),profile)\n        c["name_key"]=normalize_name(c.get("source_site_name_raw"),profile)\n        if c["address_key"]:\n            by_addr[c["address_key"]].append(c)\n            by_pair[(c["address_key"],c["name_key"])].append(c)\n    strong={k:cs for k,cs in by_pair.items() if len({x["source_key"] for x in cs})>=2}\n\n    site_rows=[]; site_by_pair={}; official_sid_by_addr={}; confirmed_name_to_sites=defaultdict(set)\n'''
new = '''    official_by_addr=defaultdict(list); official_by_locality=defaultdict(list); official_locality_by_addr={}\n    for site in profile.get("site_candidates",[]) or []:\n        if not isinstance(site,dict): continue\n        if site.get("verification_state") not in {"VERIFIED","SOURCE_VERIFIED"}: continue\n        # Discovery/profile schemas historically used VERIFIED for a site whose\n        # identity had already been source-verified, while this resolver originally\n        # accepted only CONFIRMED. Treat both as strong identity states only when the\n        # independent verification_state above is also strong.\n        if site.get("identity_status") not in {"CONFIRMED","VERIFIED","SOURCE_VERIFIED"}: continue\n        raw_address=site.get("address_raw")\n        addr=normalize_address(raw_address,profile)\n        locality=normalize_address_locality(raw_address,profile)\n        if addr: official_by_addr[addr].append(site)\n        if locality:\n            official_by_locality[locality].append(site)\n            if addr: official_locality_by_addr[addr]=locality\n    official_unique={addr:items[0] for addr,items in official_by_addr.items() if len(items)==1}\n    official_locality_unique={key:items[0] for key,items in official_by_locality.items() if len(items)==1}\n\n    # Cross-source confirmation remains available for sites that do not have a\n    # unique verified Discovery address anchor.  The locality key intentionally\n    # ignores only the top-level region, so it can bridge administrative reorganizations\n    # without silently equating weak single-source addresses.\n    by_pair=defaultdict(list); by_addr=defaultdict(list); by_locality=defaultdict(list)\n    for c in candidates:\n        c["address_key"]=normalize_address(c.get("source_address_raw"),profile)\n        c["address_locality_key"]=normalize_address_locality(c.get("source_address_raw"),profile)\n        c["name_key"]=normalize_name(c.get("source_site_name_raw"),profile)\n        if c["address_key"]:\n            by_addr[c["address_key"]].append(c)\n            by_pair[(c["address_key"],c["name_key"])].append(c)\n        if c["address_locality_key"]:\n            by_locality[c["address_locality_key"]].append(c)\n    strong={k:cs for k,cs in by_pair.items() if len({x["source_key"] for x in cs})>=2}\n    strong_locality={k:cs for k,cs in by_locality.items() if len({x["source_key"] for x in cs})>=2}\n\n    site_rows=[]; site_by_pair={}; official_sid_by_addr={}; official_sid_by_locality={}; confirmed_name_to_sites=defaultdict(set)\n'''
if old not in text:
    raise SystemExit("resolve_identity address-index anchor not found")
text = text.replace(old, new, 1)

old = '''        source_years=[y for c in by_addr.get(addr,[]) for y in c.get("years",[])]\n        yrs=years_span(source_years)\n        site_rows.append({"company_id":company_id,"canonical_site_id":sid,"canonical_site_name":name,"site_type":"UNKNOWN","country":"KR","region":"UNKNOWN","canonical_address_key":addr,"identity_status":"CONFIRMED","first_seen_year":min(yrs) if yrs else "UNKNOWN","last_seen_year":max(yrs) if yrs else "UNKNOWN","active_status":"UNKNOWN","notes":"AUTO_CONFIRMED: unique verified official Discovery address anchor"})\n        official_sid_by_addr[addr]=sid\n        if namekey: confirmed_name_to_sites[namekey].add(sid)\n'''
new = '''        locality=official_locality_by_addr.get(addr,"")\n        locality_bridge=bool(locality and locality in official_locality_unique and locality in strong_locality)\n        source_rows=list(by_addr.get(addr,[]))\n        if locality_bridge:\n            for candidate in strong_locality[locality]:\n                if candidate not in source_rows: source_rows.append(candidate)\n        source_years=[y for c in source_rows for y in c.get("years",[])]\n        yrs=years_span(source_years)\n        notes="AUTO_CONFIRMED: unique verified official Discovery address anchor"\n        if locality_bridge:\n            notes += "; admin-region continuity corroborated by >=2 independent public sources"\n        site_rows.append({"company_id":company_id,"canonical_site_id":sid,"canonical_site_name":name,"site_type":"UNKNOWN","country":"KR","region":"UNKNOWN","canonical_address_key":addr,"identity_status":"CONFIRMED","first_seen_year":min(yrs) if yrs else "UNKNOWN","last_seen_year":max(yrs) if yrs else "UNKNOWN","active_status":"UNKNOWN","notes":notes})\n        official_sid_by_addr[addr]=sid\n        if locality_bridge: official_sid_by_locality[locality]=sid\n        if namekey: confirmed_name_to_sites[namekey].add(sid)\n'''
if old not in text:
    raise SystemExit("official site row anchor not found")
text = text.replace(old, new, 1)

old = '''    for c in candidates:\n        sid=official_sid_by_addr.get(c.get("address_key"))\n        if not sid: continue\n'''
new = '''    for c in candidates:\n        sid=official_sid_by_addr.get(c.get("address_key"))\n        if not sid: sid=official_sid_by_locality.get(c.get("address_locality_key"))\n        if not sid: continue\n'''
if old not in text:
    raise SystemExit("alias bridge anchor not found")
text = text.replace(old, new, 1)

old = '''        if addr in official_sid_by_addr:\n            sid=official_sid_by_addr[addr]\n            site_by_pair[(addr,namekey)]=sid\n            if namekey: confirmed_name_to_sites[namekey].add(sid)\n            continue\n        sid=stable_id("SITE_",company_id,addr,namekey)\n'''
new = '''        if addr in official_sid_by_addr:\n            sid=official_sid_by_addr[addr]\n            site_by_pair[(addr,namekey)]=sid\n            if namekey: confirmed_name_to_sites[namekey].add(sid)\n            continue\n        locality=cs[0].get("address_locality_key","") if cs else ""\n        if locality in official_sid_by_locality:\n            sid=official_sid_by_locality[locality]\n            site_by_pair[(addr,namekey)]=sid\n            if namekey: confirmed_name_to_sites[namekey].add(sid)\n            continue\n        sid=stable_id("SITE_",company_id,addr,namekey)\n'''
if old not in text:
    raise SystemExit("strong-pair bridge anchor not found")
text = text.replace(old, new, 1)

old = '''        if (addr,namekey) in strong: continue\n        if addr in official_sid_by_addr:\n            site_by_pair[(addr,namekey)]=official_sid_by_addr[addr]\n            if namekey: confirmed_name_to_sites[namekey].add(official_sid_by_addr[addr])\n            continue\n        preferred=next((x for x in cs if x["source_key"]=="ENVINFO"),cs[0])\n'''
new = '''        if (addr,namekey) in strong: continue\n        if addr in official_sid_by_addr:\n            site_by_pair[(addr,namekey)]=official_sid_by_addr[addr]\n            if namekey: confirmed_name_to_sites[namekey].add(official_sid_by_addr[addr])\n            continue\n        locality=cs[0].get("address_locality_key","") if cs else ""\n        if locality in official_sid_by_locality:\n            site_by_pair[(addr,namekey)]=official_sid_by_locality[locality]\n            if namekey: confirmed_name_to_sites[namekey].add(official_sid_by_locality[locality])\n            continue\n        preferred=next((x for x in cs if x["source_key"]=="ENVINFO"),cs[0])\n'''
if old not in text:
    raise SystemExit("weak-pair bridge anchor not found")
text = text.replace(old, new, 1)

old = '''        elif c["address_key"] in official_sid_by_addr:\n            sid=official_sid_by_addr[c["address_key"]]; match_status="CONFIRMED"; basis="OFFICIAL_SITE_EXACT_ADDRESS"; review=False\n        elif pair in strong:\n'''
new = '''        elif c["address_key"] in official_sid_by_addr:\n            sid=official_sid_by_addr[c["address_key"]]; match_status="CONFIRMED"; basis="OFFICIAL_SITE_EXACT_ADDRESS"; review=False\n        elif c.get("address_locality_key") in official_sid_by_locality:\n            sid=official_sid_by_locality[c["address_locality_key"]]; match_status="CONFIRMED"; basis="OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS"; review=False; note=(note+"; " if note else "")+"top-level administrative region changed; lower road-address locality independently corroborated"\n        elif pair in strong:\n'''
if old not in text:
    raise SystemExit("final match bridge anchor not found")
text = text.replace(old, new, 1)

TARGET.write_text(text, encoding="utf-8")

TEST.write_text(r'''import unittest

from orchestrator.postprocess import normalize_address_locality, resolve_identity


class AdministrativeRegionAddressContinuityTests(unittest.TestCase):
    def profile(self, sites=None):
        return {
            "company_display_name": "에이치디현대삼호 주식회사",
            "aliases": [
                {"term": "에이치디현대삼호 주식회사"},
                {"term": "현대삼호중공업"},
            ],
            "related_entity_exclusions": [],
            "site_candidates": sites or [{
                "candidate_id": "yeongam-yard",
                "site_name_raw": "HD현대삼호 영암 조선소",
                "address_raw": "전남광주통합특별시 영암군 삼호읍 대불로 93",
                "identity_status": "CONFIRMED",
                "verification_state": "VERIFIED",
            }],
        }

    def old_candidates(self):
        return [
            {
                "source_key": "PRTR", "source_site_id": "618",
                "source_site_name_raw": "에이치디현대삼호(주)",
                "source_address_raw": "전라남도 영암군 삼호읍 대불로 93",
                "years": [2024], "raw_ref": "PRTR/discovery.csv",
            },
            {
                "source_key": "CHEM_STATS", "source_site_id": "AFE121N",
                "source_site_name_raw": "현대삼호중공업주식회사",
                "source_address_raw": "전남 영암군 삼호읍 대불로 93",
                "years": [2022, 2024], "raw_ref": "CHEM_STATS/discovery.csv",
            },
        ]

    def test_locality_key_survives_top_level_region_change(self):
        current = normalize_address_locality("전남광주통합특별시 영암군 삼호읍 대불로 93")
        former = normalize_address_locality("전라남도 영암군 삼호읍 대불로 93")
        abbreviated = normalize_address_locality("전남 영암군 삼호읍 대불로 93")
        self.assertEqual(current, former)
        self.assertEqual(current, abbreviated)
        self.assertEqual(current, "영암군삼호읍대불로93")

    def test_two_independent_sources_bridge_verified_admin_region_transition(self):
        _, sites, identities, validations = resolve_identity(self.old_candidates(), self.profile())
        confirmed_sites = [x for x in sites if x["identity_status"] == "CONFIRMED"]
        self.assertEqual(len(confirmed_sites), 1)
        self.assertEqual({x["match_status"] for x in identities}, {"CONFIRMED"})
        self.assertEqual(
            {x["match_basis"] for x in identities},
            {"OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS"},
        )
        self.assertFalse([x for x in validations if x.get("object_type") == "SOURCE_IDENTITY"])

    def test_single_source_does_not_auto_bridge_region_transition(self):
        _, _, identities, _ = resolve_identity(self.old_candidates()[:1], self.profile())
        self.assertEqual(len(identities), 1)
        self.assertTrue(identities[0]["review_required"])
        self.assertNotEqual(identities[0]["match_basis"], "OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS")

    def test_duplicate_official_locality_fails_closed(self):
        sites = [
            {
                "candidate_id": "a", "site_name_raw": "A 사업장",
                "address_raw": "전남광주통합특별시 중구 중앙로 1",
                "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
            },
            {
                "candidate_id": "b", "site_name_raw": "B 사업장",
                "address_raw": "부산광역시 중구 중앙로 1",
                "identity_status": "CONFIRMED", "verification_state": "VERIFIED",
            },
        ]
        candidates = [
            dict(self.old_candidates()[0], source_address_raw="전라남도 중구 중앙로 1"),
            dict(self.old_candidates()[1], source_address_raw="전남 중구 중앙로 1"),
        ]
        _, _, identities, _ = resolve_identity(candidates, self.profile(sites))
        self.assertNotIn("OFFICIAL_SITE_ADMIN_REGION_TRANSITION_ADDRESS", {x["match_basis"] for x in identities})


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("patched administrative-region address continuity and wrote regression tests")
