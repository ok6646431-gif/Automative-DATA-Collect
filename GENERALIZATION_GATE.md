# GENERALIZATION_GATE

> 목적: 기업을 바꿀 때 기존 환경정보 수집·식별·검증 파이프라인이 얼마나 재사용되는지 기록한다.  
> 원칙: 새 기업에서 결과가 불편하더라도 테스트 도중 collector/parser/orchestrator를 수정해 통과시키지 않는다.  
> 기준 브랜치: `run/control-plane`

## 1. Gate 정의

### G0 — company-name-only
- 사용자 입력은 회사명만 허용한다.
- Discovery, site scope, company documents까지 시스템이 찾아야 한다.
- 현재 프로젝트는 아직 이 수준을 입증하지 않았다.

### G1 — evidence-assisted, no-code
- 공식 Discovery/config 입력 작성은 허용한다.
- collector/parser/orchestrator 수정은 금지한다.
- 기업별 hard-code, 기업 전용 parser, validation 완화도 금지한다.

### G2 — ambiguity review
- G1에 더해 `REVIEW_REQUIRED`에 대한 사람의 확인은 허용한다.
- 사람의 확인은 코드 예외가 아니라 evidence resolution이어야 한다.

## 2. G1 판정 규칙

PASS 조건:
1. 핵심 public-source collector가 코드 수정 없이 명시적 상태(`DATA_FOUND`, `NO_DATA`, `NO_MATCH`, `UNAVAILABLE` 등)로 종료한다.
2. 요청 사업장 scope가 확인되거나, 불확실하면 `REVIEW_REQUIRED`로 남는다.
3. 법인 변경·분할·합병이 확인된 경우 서로 다른 법인의 자료를 이름/주소/source ID가 같다는 이유만으로 자동 연속시계열로 합치지 않는다.
4. 같은 주소에 다른 법인/계열사 시설이 있어도 요청 법인/사업장 scope로 자동 편입하지 않는다.
5. 외부 source 장애는 retry/replay/provenance 또는 명시적 unavailable 상태로 처리한다.
6. package/archive가 구조적으로 생성된다.
7. 기존 workflow의 운영 예산을 기업별 예외 없이 지킨다. 현재 `stable_sources` 상한은 45분이다.

PARTIAL PASS:
- core collection/identity/package는 통과하지만 company-document enrichment 등 비핵심 영역에 외부 URL/공개성 문제 또는 추가 evidence review가 남는다.

FAIL:
- 새 parser/collector 예외/기업별 hard-code가 필요하다.
- 잘못된 company/site/legal-entity continuity를 자동 확정한다.
- 관련 없는 계열사/별도 법인 시설을 requested analysis scope로 편입한다.
- 일반 workflow 운영 예산을 기업 규모 때문에 반복적으로 초과한다.

## 3. Generalization test register

### Hyundai Motor — G1 PARTIAL PASS
- 평가 Run: `33231709238` (#127)
- Commit: `6e5eeabab9d49dfd851b7066e833426012cfc078`
- Workflow conclusion: `success`
- 신규 parser: 0
- collector/orchestrator 수정: 0
- 기업별 runtime hard-code: 0
- core sources: ENV-INFO / PRTR / Chemical Statistics / CleanSYS가 기존 코드로 수집, SOOSIRO는 명시적 no-match 처리
- ENV-INFO의 기존 generic attachment recovery/dedup 규칙도 재사용됨
- company-document enrichment는 일부 공식 보고서 직접 다운로드가 실패하여 `PARTIAL_DOWNLOAD`
- 결론: **G1 PARTIAL PASS**. Core 환경자료 수집·scope·package 일반화는 통과했으나 enrichment는 아직 완전 zero-touch가 아님.

### POSCO — G1 FAIL

#### Test identity
- 평가 Run: `33232906478` (#131)
- Commit: `826eb5ae86ccda8794c26470df54796483bf9c38`
- Workflow conclusion: `success`
- 요청 scope: 포항제철소 + 광양제철소
- Discovery evidence: 현 `주식회사 포스코` active period를 2022~로 기록하고, 2022-03-01 물적분할 전 자료는 자동 승계하지 말 것을 명시함.
- 테스트 중 collector/parser/orchestrator 수정: 0

#### Collection portability — PASS
- PRTR `DATA_FOUND`: 71 rows, detail 71/71, detail table 1,878 rows, errors 0
- Chemical Statistics `DATA_FOUND`: 93 rows, 43 unique business-site IDs, detail 93/93, detail table 7,635 rows, errors 0
- ICIS gate `PASS`; retry/replay 불필요
- ENV-INFO `DATA_FOUND`: 124 rows, 33 unique COMP_ID, detail 124/124
- ENV-INFO attachments: 733 discovered; recovery 후 336 확보, 63 deduplicated, 215,036,751 bytes duplicate saved, 397 explicit budget skips, remaining failure 0
- SOOSIRO `DATA_FOUND`: annual rows 74, daily rows 4,026, errors 0
- CleanSYS `DATA_FOUND`: candidates 12, annual rows 64, years 2020~2025
- corporate documents: 6 declared / 6 downloaded / failures 0; Discovery gaps 4
- `stable_sources`는 약 38분 57초에 완료하여 45분 운영 상한 내 통과. 다만 ENV-INFO 본수집 약 21분 55초 + recovery 약 13분 8초로 **PERFORMANCE_REVIEW** 대상.
- package/archive도 구조적으로 생성되었고 `package_health=PASS`, `validation=REVIEW_REQUIRED`로 종료함.

#### Failure A — `TEMPORAL_LEGAL_ENTITY_BOUNDARY`
- raw evidence에서 포항/광양 핵심 source ID가 2020~2024에 걸쳐 이어짐.
- `company_profile_builder.py`는 current legal name alias에 `year_start=2022`를 보존하지만, `postprocess.py` identity resolution은 source candidate의 관측연도를 `valid_from/valid_to`로 사용하고 legal-entity active period를 적용하지 않음.
- `requested_scope.py`도 canonical/source ID로 analysis scope를 선택하고 row year/legal-entity validity를 검사하지 않음.
- 최종 `Source_Identity.csv` 실제 결과:
  - CHEM_STATS `ABZ562N` 포항제철소: `CONFIRMED`, `valid_from=2020,2022,2024`
  - CHEM_STATS `ACA106N` 광양제철소: `CONFIRMED`, `valid_from=2020,2022,2024`
  - PRTR `813618` 광양제철소: `CONFIRMED`, `valid_from=2020`, `valid_to=2024`
- 최종 `Analysis_Ready_Index.csv` requested scope에는 2020 row 24개, 2021 row 20개가 남았으며, CHEM_STATS 포항/광양의 2020 rows는 `analysis_eligible=True`까지 부여됨.
- `Review_Metric_Inventory.csv`의 in-scope 157개 metric 중 120개 series가 2020을 포함하고 124개가 2021을 포함함.
- `Chemical_Review_Candidates.csv`에는 여러 물질이 `years=2020|2021|2022|2023|2024`의 5년 연속 current-scope series로 생성됨.
- 따라서 알려진 2022 법인 경계를 실제 downstream analysis가 지키지 못함.

#### Failure B — `COLOCATED_RELATED_ENTITY_SCOPE_LEAK`
- 최종 `Requested_Scope.json`은 포항·광양제철소 두 곳만 요청했지만, target source IDs에 별도 법인/계열사 시설이 포함됨.
- 예:
  - ENVINFO `(주)포스코퓨처엠 라임공장(포항)` / `00000000000000150930`
  - ENVINFO `(주)포스코퓨처엠 라임공장(광양)` / `00000000000000150950`
  - PRTR `(주)포스코켐텍 포항화학사업부(LIME)` / `1250145083732162149`
  - PRTR `(주)포스코케미칼 광양사무소` / `2011162`
  - CHEM_STATS `(주)포스코켐텍포항화학사업부` / `ABP345N`
  - CHEM_STATS `(주)포스코케미칼` / `ADP261N`
  - CHEM_STATS `포스코플랜텍` / `AER157N`
- 이 source identities는 대부분 `REVIEW_REQUIRED`인데도, `requested_scope.py`가 unique requested-site address에서 `address_match OR name_match`를 허용하여 동해안로 6262 / 폭포사랑길 20-26 등 제철소와 같은 주소의 별도 법인 시설까지 target source ID로 넣음.
- 결과적으로 `Review_Metric_Inventory.csv`에서 포스코퓨처엠 라임공장만 **30개 metric이 `in_requested_scope=YES`**로 들어갔고, 다수가 `TREND_ELIGIBLE`로 분류됨.
- `Review_Topic_Candidates.csv`에는 포스코퓨처엠 라임공장(포항/광양) 명의 주제가 **7건** 생성됨.
- 따라서 G1의 “요청 법인/사업장과 별도 법인을 같은 주소만으로 포함하지 않는다” 조건을 위반함.

#### Final verdict
- GitHub CI/workflow: **SUCCESS**
- Collector/parser portability: **PASS**
- Runtime budget: **PASS with PERFORMANCE_REVIEW**
- Legal-entity temporal identity: **FAIL**
- Requested-scope legal-entity boundary: **FAIL**
- Overall Generalization Gate: **G1 FAIL**

`CI success != Generalization PASS`. 포스코 전용 예외를 추가하지 않고 두 문제 모두 범용 identity/scope 결함으로 등록한다.

## 4. Intervention Ledger

| 최초 발견 기업/상황 | 문제 유형 | 당시 조치 | 기업 전용 조치인가 | 이후 재사용 상태 |
|---|---|---|---|---|
| Hanwha Aerospace | ENV-INFO zero-result 뒤 stale DOM row를 결과로 오인 | explicit zero-result가 stale DOM보다 우선하도록 수집 검증 강화 | 아니오 | 일반 규칙으로 유지 |
| Kumho Petrochemical | ENV-INFO 중복 첨부가 500 MiB logical budget을 소진하여 후속 첨부를 `DOWNLOAD_FAILED`로 오분류 | SHA dedup + unique-byte budget + recovery + budget skip 상태 분리 | 아니오 | Hyundai/POSCO에서 수정 없이 재사용 성공 |
| ICIS outage | PRTR/Chem Stats 외부 호스트 timeout | 3회 retry 후 exact query fingerprint가 맞는 최근 성공본만 provenance replay | 아니오 | fresh/replay 두 경로 실데이터 QA 통과 |
| Kumho Petrochemical | K-BREF/회사문서 외부 저장소 timeout·catalog-only | 공식 source 우선, direct PDF 검증, unavailable/review 상태 유지 | 아니오 | source-availability 규칙으로 유지 |
| Kumho Petrochemical semantic QA | 같은 AIR/WATER 대분류라는 이유로 서로 다른 세부 이슈를 FOUR_LAYER_READY로 연결 | semantic bridge gate; 세부 pollutant/issue 연결 요구 | 아니오 | 회귀테스트에 고정 |
| Hyundai Motor #127 | 새로운 완성차 기업 | **코드 수정 없음** | 해당 없음 | G1 PARTIAL PASS |
| POSCO #131 | 2022 물적분할 전후 동일 site/source ID의 legal-entity continuity | 테스트 중 수정 금지; 범용 temporal identity gate 필요성을 발견 | 아니오 — 분사/합병/물적분할 기업 공통 | **G1 FAIL; generic defect** |
| POSCO #131 | 같은 제철소 주소의 포스코퓨처엠/포스코케미칼/켐텍/플랜텍 source가 requested scope로 누출 | 테스트 중 수정 금지; 법인 일치 + site evidence를 함께 요구하는 scope gate 필요 | 아니오 — 복합산단/공장내 별도법인 공통 | **G1 FAIL; generic defect** |

## 5. POSCO가 드러낸 범용 결함

### A. `TEMPORAL_LEGAL_ENTITY_BOUNDARY`
현재 시스템은 다음 둘을 충분히 분리하지 않는다.
1. **physical/site continuity**: 같은 제철소·주소·source-native facility ID가 여러 해 이어지는가.
2. **legal-entity continuity**: 그 해의 환경자료를 현재 요청한 법인의 자료로 귀속해도 되는가.

포스코 사례에서는 site continuity가 있어도 2022-03-01 전후 법인이 동일하지 않다. 따라서 site continuity만으로 current-company continuity를 만들면 안 된다.

### B. `COLOCATED_RELATED_ENTITY_SCOPE_LEAK`
현재 requested-scope resolver는 verified site address가 unique하면 address match만으로 source row를 requested scope에 포함할 수 있다. 대형 산업단지/제철소처럼 한 주소 안에 여러 별도 법인 시설이 존재할 때는 이 규칙이 과도하다.

## 6. 다음 수정의 범용 요구사항

테스트 종료 후에만 수정한다.

### Temporal entity gate
- raw collector evidence는 그대로 보존한다.
- source/site identity와 legal-entity temporal applicability를 별도 상태로 가진다.
- 현재 법인의 `active_period` 이전 row는 current-company analysis에서 자동 제외하거나 `TEMPORAL_ENTITY_REVIEW`로 보류한다.
- predecessor→current continuity가 공식적으로 별도 확인된 경우에만 명시적 evidence link를 통해 연결한다.
- requested scope filtering은 source ID만 보지 말고 row year와 entity-validity를 함께 검사한다.

### Co-located entity gate
- verified official site 주소와 일치해도 source-native company/legal-entity 명칭이 요청 법인과 충돌하면 address-only inclusion을 금지한다.
- `REVIEW_REQUIRED` source identity를 requested scope에 보존할 수는 있지만, 별도 법인 신호가 있으면 analysis/display에서 자동 제외하고 `RELATED_ENTITY_REVIEW`로 남긴다.
- 긴 brand token(`포스코`)의 substring만으로 계열사를 current company로 인정하지 않는다.
- 공장내 별도 법인, 협력사, 계열사, 분사법인이 공유주소를 사용할 수 있음을 일반 규칙으로 취급한다.

### 필수 회귀테스트
1. 2022 신설 법인 + 동일 source ID의 2020/2021/2022/2023 rows
2. 2020/2021 raw 보존
3. current-company analysis에서는 2020/2021 자동 제외/보류
4. 2022+ rows 정상 포함
5. explicit predecessor continuity evidence가 없으면 자동 merge 금지
6. 같은 주소에 `현재법인 제철소`와 `계열사 라임공장` 동시 존재
7. 계열사 raw는 보존하지만 requested current-company analysis에는 포함하지 않음
8. 동일 법인의 source-native 이름 변형은 기존 exact-address/name evidence로 정상 포함

## 7. 현재 범용성 판단

- **collector/parser portability는 강하다.** Hyundai와 POSCO 모두 새 collector/parser 없이 core public-source 수집을 완료했다.
- 과거 기업에서 만든 generic attachment recovery/retry/fail-closed 규칙이 새 기업에서 실제 재사용되고 있다.
- 그러나 **corporate restructuring의 시간축 identity**와 **공유주소 내 별도 법인 scope boundary**는 아직 generalization gap이다.
- 따라서 현재 프로젝트를 `회사명만 넣으면 항상 완전 자동으로 정확한 장기시계열을 만드는 universal zero-touch system`이라고 부르면 과장이다.
- 현재의 더 정확한 정의는 **공식 공개 환경자료 수집·검증의 반복 작업을 자동화하고, 법인/사업장/근거의 불확실성을 명시적으로 사람이 검토할 수 있게 만드는 AI-assisted environmental research framework**이다.

다음 blind test는 두 identity/scope gate를 범용 규칙으로 수정하고 기존 회사 회귀테스트를 통과한 뒤 실시한다.
