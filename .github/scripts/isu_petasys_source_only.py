#!/usr/bin/env python3
"""Build a source-only request from *already observed* first-party/DART evidence.

Recovery is deliberately isolated: it does not promote G0, alter tracked current
company requests, claim annual reports were downloaded, or mark invented sites
VERIFIED. The G0 artifact's misparsed site names are not used.
"""
import json
import sys
from pathlib import Path
from orchestrator.company_profile_builder import compile_discovery
from orchestrator.request_builder import build

source=Path(sys.argv[1])
target=Path(sys.argv[2])
target.mkdir(parents=True,exist_ok=True)
discovery=json.loads((source/"company_discovery.json").read_text(encoding="utf-8"))
audit=json.loads((source/"Discovery_Audit.json").read_text(encoding="utf-8"))
legal=(((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
required={
    "select_key":"00107613",
    "korean_name":"(주)이수페타시스",
    "website":"www.petasys.com",
}
for key,expected in required.items():
    if str(legal.get(key) or "") != expected:
        raise SystemExit("ABORT: G0 source does not establish the intended DART entity: "+key)
if str(discovery.get("current_legal_name") or "") != required["korean_name"]:
    raise SystemExit("ABORT: G0 Discovery and DART identity mismatch")
assert "Nongong-ro 53-gil" in str(legal.get("address") or ""), "DART headquarters address missing"
if str(discovery.get("company_verification_state") or "") != "VERIFIED":
    raise SystemExit("ABORT: legal identity is not VERIFIED")
# First-party sustainability report and KRX quarterly filing both identify the
# Daegu headquarters as Nongong-ro 53-gil 36; DART independently verifies it.
# Do NOT retain the "고객과 공장" website-text parsing false positive.
discovery["domestic_site_candidates"]=[{
    "candidate_id":"dart-00107613-headquarters",
    "site_name_raw":"본사",
    "address_raw":"대구광역시 달성군 논공읍 논공로 53길 36",
    "source_locator":str(legal.get("source_url") or ""),
    "identity_status":"CONFIRMED",
    "verification_state":"VERIFIED",
    "discovery_evidence":{
        "evidence_type":"DART_INDEPENDENT_OFFICIAL_HEADQUARTERS",
        "dart_source_url":str(legal.get("source_url") or ""),
        "raw_dart_address":legal["address"],
        "corroborating_report":"https://www.petasys.com/kor/csr/report_2021.pdf",
        "limitations":"Not a complete list of production facilities; source-native public registries must independently resolve facility IDs."
    }
}]
discovery["requested_scope"]={"mode":"COMPANY","label":"(주)이수페타시스 company-wide public registry discovery",
 "raw_collection_policy":"PRESERVE_COMPANY_WIDE"}
# Keep the original G0 source/period policy; do not claim document completeness.
profile,summary=compile_discovery(discovery)
if summary.get("review_required_count"):
    raise SystemExit("ABORT: source-only identity compilation unresolved: "+
                     json.dumps(summary,ensure_ascii=False)[:2000])
profile["requested_scope"]=discovery["requested_scope"]
request=build(profile)
identity=(request["sources"]["ENVINFO"]["identity_gate"])
if not identity.get("verified_sites") or identity["verified_sites"][0]["address"] != "대구광역시 달성군 논공읍 논공로 53길 36":
    raise SystemExit("ABORT: corrupted source-native identity gate")
(target/"company_discovery.source_only.json").write_text(json.dumps(discovery,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
(target/"profile.json").write_text(json.dumps(profile,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
(target/"request.json").write_text(json.dumps(request,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
(target/"identity_evidence.json").write_text(json.dumps({"source_key":"DART","status":"VERIFIED",
 "legal_name":legal["korean_name"],"dart_locator":legal["source_url"],
 "site_scope":"DART-verified headquarters only, registry discovery may find additional sites",
 "excluded_unverified_G0_sites":2,
 "official_source_anchor":"https://www.petasys.com/kor/csr/report_2021.pdf"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"company":profile["company_display_name"],
 "request_id":request["request_id"],"verified_sites":identity["verified_sites"],
 "sources":list(request["sources"]),"discovery_reviews":summary.get("review_required_count")},ensure_ascii=False))
