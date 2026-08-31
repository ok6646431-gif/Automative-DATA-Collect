import json
from pathlib import Path

REQ="kumho-petrochemical-env-20260831-v1"
OFFICIAL_NETWORK="https://www.kkpc.com/kor/company/global/global/"
OFFICIAL_COMPANY="https://www.kkpc.com/kor/company/intro/intro/"

sites=[
("kkpc-ulsan-rubber","울산고무공장","울산광역시 남구 상개로 64(상개동)","SBR, NBR, SB/NB-Latex 등 합성고무 생산"),
("kkpc-ulsan-resin","울산수지공장","울산광역시 남구 처용로 260-257(성암동)","PS, ABS, EPS, PPG, SAN 등 합성수지 생산"),
("kkpc-ulsan-latex-1","울산 LATEX 1공장","울산광역시 남구 상개로 64(상개동)","PCL, MPL, NB-Latex 생산"),
("kkpc-ulsan-latex-2","울산 LATEX 2공장","울산광역시 남구 처용로 260-257(성암동)","NB-Latex 생산"),
("kkpc-yeosu-rubber-1","여수고무제1공장","전라남도 여수시 여수산단3로 118(평여동)","BR, SSBR, NdBR, SBS 등 합성고무 생산"),
("kkpc-yeosu-rubber-2","여수고무제2공장","전라남도 여수시 산단중앙로 331(평여동)","BR, SSBR 등 합성고무 생산"),
("kkpc-yeosu-fine-chemical","여수정밀화학공장","전라남도 여수시 여수산단2로 227(화치동)","노화방지제, 가황촉진제 등 정밀화학 생산"),
("kkpc-yeosu-energy-1","여수제1에너지","전라남도 여수시 여수산단2로 46-51(월하동)","증기, 전기 생산"),
("kkpc-yeosu-energy-2","여수제2에너지","전라남도 여수시 여수산단2로 223-84(화치동)","증기, 전기 생산"),
("kkpc-yeosu-energy-3","여수제3에너지","전라남도 여수시 율촌면 여동리 율촌제1산단 2-5블록","증기, 전기 생산"),
("kkpc-yesan-building-material","예산건자재공장","충청남도 예산군 고덕면 예덕로 1033-9(호음리)","건자재 생산"),
("kkpc-hwaseong-insulation","화성단열재공장","경기도 화성시 정남면 발안로 1093(덕절리)","단열재 생산"),
("kkpc-yulchon-cnt","율촌CNT공장","전라남도 여수시 율촌면 율촌산단6로 115","탄소나노튜브(CNT) 생산"),
]

profile={
"schema_version":"1.0",
"request_id":REQ,
"requested_company_name":"금호석유화학",
"current_legal_name":"금호석유화학",
"company_verification_state":"VERIFIED",
"confidence":"HIGH",
"requested_scope":{
  "mode":"SITE_SET",
  "label":"금호석유화학 국내 생산공장 13개 전체",
  "candidate_ids":[s[0] for s in sites],
  "raw_collection_policy":"PRESERVE_COMPANY_WIDE",
  "archive_policy":"FILTER_TO_REQUESTED_SCOPE",
  "analysis_policy":"FILTER_TO_REQUESTED_SCOPE"
},
"scope_notes":[
 {"code":"OFFICIAL_PRODUCTION_NETWORK_SCOPE","subject":"금호석유화학 국내 생산공장 13개","detail":"금호석유화학 공식 글로벌 네트워크 페이지가 생산공장으로 명시한 국내 13개 시설 전체를 환경자료 핵심 범위로 사용한다."},
 {"code":"COLOCATED_SITE_NAMES_REQUIRE_SOURCE_IDENTITY","subject":"울산 LATEX 1·2공장","detail":"LATEX 1은 울산고무공장과, LATEX 2는 울산수지공장과 공식 주소가 동일하므로 주소만으로 자동 병합하지 않고 사업장명·source ID를 함께 검증한다."}
],
"company_aliases":[
 {"name":"금호석유화학","alias_type":"current_brand_and_legal_name","verification_state":"VERIFIED","source_locator":OFFICIAL_COMPANY},
 {"name":"금호석유화학(주)","alias_type":"source_native_alias","verification_state":"SOURCE_VERIFIED","source_locator":OFFICIAL_COMPANY},
 {"name":"금호석유화학㈜","alias_type":"source_native_alias","verification_state":"SOURCE_VERIFIED","source_locator":OFFICIAL_COMPANY},
 {"name":"금호석유화학 주식회사","alias_type":"expanded_legal_alias","verification_state":"SOURCE_VERIFIED","source_locator":OFFICIAL_COMPANY},
 {"name":"KUMHO PETROCHEMICAL","alias_type":"english_name","verification_state":"VERIFIED","source_locator":OFFICIAL_COMPANY},
 {"name":"Kumho Petrochemical Co., Ltd.","alias_type":"english_source_alias","verification_state":"SOURCE_VERIFIED","source_locator":OFFICIAL_COMPANY}
],
"historical_legal_names":[],
"corporate_restructuring_evidence":[],
"domestic_site_candidates":[
 {"candidate_id":cid,"site_name_raw":name,"address_raw":addr,"business_unit_raw":biz,"source_locator":OFFICIAL_NETWORK,"identity_status":"VERIFIED","verification_state":"VERIFIED"}
 for cid,name,addr,biz in sites
],
"identity_evidence":[
 {"source_locator":OFFICIAL_NETWORK,"source_value_raw":"금호석유화학 공식 글로벌 네트워크의 국내 생산공장 명칭·주소·생산기능","verification_state":"VERIFIED"},
 {"source_locator":OFFICIAL_COMPANY,"source_value_raw":"회사명 금호석유화학, 사업: 합성고무·합성수지·정밀화학·나노탄소·에너지·건자재","verification_state":"VERIFIED"}
],
"related_entity_exclusions":[
 {"name":"금호피앤비화학","reason":"금호석유화학과 별도 법인","source_locator":"https://www.kkpc.com/kor/company/global/global/","verification_state":"VERIFIED"},
 {"name":"금호폴리켐","reason":"금호석유화학과 별도 법인","source_locator":"https://www.kkpc.com/kor/company/global/global/","verification_state":"VERIFIED"},
 {"name":"금호미쓰이화학","reason":"금호석유화학과 별도 법인","source_locator":"https://www.kkpc.com/kor/company/global/global/","verification_state":"VERIFIED"},
 {"name":"금호티앤엘","reason":"금호석유화학과 별도 법인","source_locator":"https://www.kkpc.com/kor/company/global/global/","verification_state":"VERIFIED"}
],
"unresolved_items":[],
"event_evidence_references":[],
"collection_policy":{
 "minimum_history_years":5,
 "sources":{
  "ENVINFO":{"requested_window":{"start_year":2020,"end_year":2024},"prefer_full_history":False,"max_details":500},
  "PRTR":{"requested_window":{"start_year":2020,"end_year":2024},"prefer_full_history":False},
  "CHEM_STATS":{"requested_survey_rounds":[2020,2022,2024],"available_survey_rounds":[2020,2022,2024],"prefer_full_history":True},
  "CLEANSYS_AIR":{"requested_window":{"start_year":2020,"end_year":2025},"prefer_full_history":False},
  "SOOSIRO_WATER":{"requested_window":{"start_year":2020,"end_year":2025},"daily_available_years":[2024],"prefer_full_history":False}
 }
}
}
Path("requests/company_discovery.json").write_text(json.dumps(profile,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

p=Path("requests/industry_reference_applicability.json")
if p.exists():
    d=json.loads(p.read_text(encoding="utf-8"))
    d["request_id"]=REQ
    for r in d.get("references",[]):
        if r.get("document_id")=="NIER_ENERGY_KBREF_II_2022":
            r["candidate_ids"]=["kkpc-yeosu-energy-1","kkpc-yeosu-energy-2","kkpc-yeosu-energy-3"]
            r["basis"]="금호석유화학 공식 글로벌네트워크는 여수제1·2·3에너지의 기능을 증기·전기 생산으로 명시하고, 국립환경과학원 IEPS는 '전기 및 증기 생산시설의 환경오염방지 및 통합관리를 위한 최적가용기법 기준서(Ⅱ)'를 공식 공개한다. 이는 기술기준서의 참고 적용 가능성만 뜻하며 개별 사업장의 허가조건 또는 BAT 채택을 의미하지 않는다."
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

# Keep non-collection evidence request-consistent but empty for this acceptance run.
for fn in ("event_evidence.json",):
    q=Path("requests")/fn
    if q.exists():
        old=json.loads(q.read_text(encoding="utf-8"))
        old["request_id"]=REQ
        if "events" in old: old["events"]=[]
        if "evidence" in old: old["evidence"]=[]
        if "gaps" in old: old["gaps"]=[]
        q.write_text(json.dumps(old,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

print(json.dumps({"request_id":REQ,"site_count":len(sites),"candidate_ids":[s[0] for s in sites]},ensure_ascii=False))
