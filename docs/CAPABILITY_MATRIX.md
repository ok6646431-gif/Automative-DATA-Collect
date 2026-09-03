# Environmental Data Automation Capability Matrix

이 문서는 기업별 예외 목록이 아니라 **zero-touch 환경자료 수집 시스템이 일반적으로 처리할 수 있는 문제 유형**을 관리한다.

상태 정의:
- `VERIFIED`: 단위/회귀테스트와 실제 기업 E2E에서 확인됨
- `IMPLEMENTED`: 일반 로직과 회귀테스트는 있으나 충분한 실제 기업 교차검증이 더 필요함
- `PARTIAL`: 일부 구성요소만 구현됨
- `NOT_IMPLEMENTED`: 의도적으로 아직 구현하지 않음

## Capability matrix

| Capability ID | 문제 유형 | 일반 동작 | 실패 정책 | 주요 회귀테스트 | Live 검증 기업 | 상태 |
|---|---|---|---|---|---|---|
| G0-LEGAL-IDENTITY | 입력 회사명과 법인 식별 | DART 원문에서 현재 법인을 검증하고 별도 법인 후보를 분리 | 법인을 유일하게 확정하지 못하면 REVIEW_REQUIRED | `test_dart_public_resolver.py`, `test_zero_touch_discovery.py` | HD현대삼호, 한화오션 | VERIFIED |
| G0-RENAME-CONTINUITY | 사명변경 전후 과거자료 | 공식 공시의 구상호, 신상호, 변경일을 확인해 연도별 검색어를 분리 | rename 신호만 있고 predecessor/date가 없으면 차단 | `test_g0_kind_disclosure_recovery.py`, `test_rename_continuity_contract.py` | HD현대삼호, 한화오션 | VERIFIED |
| G0-STALE-OFFICIAL-URL | DART 등록 홈페이지가 구형/죽은 경로 | 동일 host의 경로 상위와 root를 먼저 복구하고, 필요할 때만 외부 후보를 1차 출처에서 재검증 | 공식 경계를 재확인하지 못하면 REVIEW_REQUIRED | `test_g0_official_site_recovery.py` 계열 G0 regressions | 한화오션, HD현대삼호 | VERIFIED |
| G0-ESG-SUBDOMAIN | ESG/지속가능경영 별도 공식 host | 본사 공식 사이트가 직접 연결하고 같은 조직임을 검증한 문서 host만 추가 탐색 | 임의 서브도메인 추정 금지 | `test_g0_report_enrichment.py` | 한화오션 | IMPLEMENTED |
| G0-SCRIPTED-PDF | JavaScript/token 기반 PDF 다운로드 | 공식 페이지의 다운로드 함수 계약을 해석하고 최종 `%PDF` 바이트를 검증 | HTML/오류응답은 문서로 승격하지 않음 | `test_g0_scripted_report_enrichment.py`, `test_g0_scripted_report_navigation.py` | 한화오션 | VERIFIED |
| G0-REPORT-SEMANTICS | 브로슈어/IR PDF의 보고서 오분류 | 지속가능/통합/ESG 보고서 의미가 강한 PDF만 연차 series로 승격 | brochure/catalog/IR 등은 연도와 PDF 여부만으로 승격 금지 | `test_g0_report_enrichment.py`, `test_capability_regression_corpus.py` | 한화오션 | VERIFIED |
| DOC-ANNUAL-COVERAGE | 최신 몇 년만 찾고 과거 연차 누락 | 요청 history 전체 연차를 검사하고 공식 NOT_PUBLISHED만 gap 해소로 인정 | 검증되지 않은 연도 누락은 blocking gap | `test_collection_completeness.py` | HD현대삼호, 한화오션 | VERIFIED |
| SOURCE-LEGAL-NAME-VARIANTS | `(주)`, `㈜`, `주식회사` 등 공공DB 표기 차이 | 검증된 legal alias에서만 표기 변형을 생성하고 동일 연도 경계를 유지 | brand에 임의 법인 접미사 생성 금지 | `test_request_builder.py` | HD현대삼호, 한화오션 | VERIFIED |
| G0-PREDECESSOR-ISOLATION | 분사/합병 predecessor를 현재 법인 검색어로 오인 | `scope=predecessor` alias는 모든 company-wide collector에서 기본 제외하고 별도 continuity 검증 없이는 검색하지 않음 | 모회사/피합병법인 전체 자료 자동 상속 금지 | `test_request_builder.py`, capability CI | LG에너지솔루션 live 검증 예정 | IMPLEMENTED |
| SITE-ADMIN-REGION-CONTINUITY | 행정구역 개편으로 주소 앞부분 변경 | 하위 행정구역+도로주소의 보수적 suffix가 유지될 때 동일 site 후보로 연결 | 짧은 도로번호 일치만으로 결합 금지 | `test_admin_region_address_continuity.py`, `test_requested_scope_rename_bridge.py` | HD현대삼호 | VERIFIED |
| SITE-BILINGUAL-ADDRESS-CONTINUITY | 공식 영문주소와 공공DB 한글주소 | 3~4자리 도로/건물번호, 동일 법인, 2개 이상 독립 source, 유일한 canonical site가 동시에 성립할 때만 bridge | 후보가 둘 이상이면 자동결합 금지 | `test_requested_scope_bilingual_bridge.py`, `test_capability_regression_corpus.py` | 한화오션 | VERIFIED |
| SITE-SAME-ENTITY-FACILITY-LABEL | `회사명 거제사업장`을 별도 법인으로 오인 | 동일 법인명 뒤의 보수적인 일반 `...사업장` 표기는 legal-entity compatible로 허용하되 실제 scope 포함에는 주소 근거를 추가 요구 | 센터/사무소/현장/임의 suffix를 동일 규칙으로 자동 포함하지 않음 | `test_requested_scope_bilingual_bridge.py` | 한화오션 | VERIFIED |
| SITE-MULTI-SITE-SCOPE | company-wide raw와 사용자 요청 사업장 분리 | raw는 전체 보존, delivery/analysis만 requested SITE_SET으로 필터 | 원천자료 삭제 금지 | `test_requested_scope_rename_bridge.py`, archive/package tests | HD현대삼호, 한화오션 | VERIFIED |
| RELATED-ENTITY-EXCLUSION | 유사 회사명/관계사 혼입 | verified related entity 또는 same-entity rule을 충족하지 못한 source identity는 user scope에서 제외 | 회사명 prefix만으로 동일 법인 인정 금지 | `test_requested_scope_bilingual_bridge.py`, `test_capability_regression_corpus.py` | 한화오션: 에코텍 raw 보존, user layer 0건 | VERIFIED |
| ARCHIVE-RAW-VS-USER-LAYER | raw evidence와 전달자료 혼재 | 원천 company-wide evidence는 보존하고 Human Archive/application package는 requested scope만 제공 | 제외 근거 metadata는 보존 가능, 실제 off-scope 자료는 user layer 금지 | application/archive validation tests | HD현대삼호, 한화오션 | VERIFIED |
| ARCHIVE-REQUESTED-SCOPE | source ID를 requested canonical site에 결합 | Site_Master + Source_Identity + verified Discovery evidence로 source별 target ID 생성 | identity 불명확 시 분석/전달에서 제외 또는 review | requested-scope tests | HD현대삼호, 한화오션 | VERIFIED |
| ARCHIVE-NONEMPTY-BINDING | raw에는 데이터가 있는데 SITE_SET source ID가 0인 false COMPLETE | data-bearing source마다 target ID가 없으면 `REQUESTED_SCOPE_SOURCE_BINDING_UNRESOLVED` 생성 | COMPLETE 금지 | `test_requested_scope_completeness_guard.py`, `test_capability_regression_corpus.py` | 한화오션에서 결함 발견 후 보강 | VERIFIED |
| SOURCE-RETRY-OUTAGE | 외부 공공시스템 일시 장애 | bounded retry/replay 후 성공 증거와 실패 상태를 분리 | 조회 실패를 NO_DATA로 변환 금지 | collection/replay tests | 한화오션 ICIS retry | IMPLEMENTED |
| G0-SPINOFF-CONTINUITY | 분사 전후 어느 자료가 신설 법인에 귀속되는지 | predecessor 자동상속은 차단했으며, 향후 자산/사업/사업장 continuity evidence로 site/source 단위 귀속을 검증 | 모회사 과거자료를 신설법인의 historical alias로 자동 상속 금지 | predecessor isolation 구축, site continuity 미구축 | LG에너지솔루션 예정 | PARTIAL |
| G0-MERGER-MA-CONTINUITY | 합병/사업양수도/법인 통합 | predecessor를 alias가 아니라 별도 법인 event로 관리하고 site/source 귀속을 기간별 검증 | predecessor company-wide 자료 자동 편입 금지 | 일부 event/scope tests | 한화에어로스페이스 예정 | PARTIAL |
| SITE-LARGE-MULTI-SITE | 대형 복수 사업장과 공통 법인명 row | 빈 site label을 모든 사업장에 매칭하지 않고 사업장별 source ID를 유지 | 법인명만 있는 row의 무차별 site 결합 금지 | requested-scope/site identity tests | 삼성전자, SK하이닉스 추가 검증 예정 | PARTIAL |

## 한화오션 live baseline

- 재조립 검증 run: `33726982925`
- 요청 scope source ID: ENV-INFO `00000000000000185726`, PRTR `414`, CHEM_STATS `ACW978N`
- scope 적용 후 분석행: `10`, off-scope 분석행: `0`
- Collection Completeness: `COMPLETE`, 43/43 items complete
- Human Archive: `COMPLETE`, user files 50, system files 214
- 관련법인 증거는 `90_시스템원본`에 보존되며 실제 user-facing 영역의 한화오션에코텍 hit는 `0`
- Human Archive SHA256: `9bbbc5a13a556c80451d014cbe415b99e8fdb05b1d1512cd9aeaa1a8d72a4505`
- 검증 artifact ID: `9882400415`

## 운영 원칙

1. 새 기업에서 문제가 발생하면 먼저 기존 Capability ID에 해당하는지 분류한다.
2. 기존 capability의 버그라면 generic code와 regression test를 수정한다.
3. 기존 capability로 표현할 수 없는 경우에만 새 Capability ID를 만든다.
4. 회사명 하드코딩은 production generic layer에 넣지 않는다.
5. 처음 보는 구조를 해결하지 못하는 것은 허용하지만, 잘못된 `PASS`는 허용하지 않는다.
6. `collector success`, `requested-scope success`, `Human Archive COMPLETE`, `application package PASS`는 서로 다른 상태로 기록한다.

## 성숙도 지표

새 회사 batch마다 아래를 기록한다.

- 자동 PASS 기업 수
- legitimate REVIEW_REQUIRED 기업 수
- 기존 capability bug 수
- 신규 capability gap 수
- 기업별 production code exception 수 — 목표는 항상 0
- 새 기업 1개당 generic code change 수

시스템이 성숙할수록 **새 기업 1개당 generic code change 수와 신규 capability gap 수가 감소**해야 한다.
