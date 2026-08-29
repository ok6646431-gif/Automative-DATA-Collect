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
4. 외부 source 장애는 retry/replay/provenance 또는 명시적 unavailable 상태로 처리한다.
5. package/archive가 구조적으로 생성된다.
6. 기존 workflow의 운영 예산을 기업별 예외 없이 지킨다. 현재 `stable_sources` 상한은 45분이다.

PARTIAL PASS:
- core collection/identity/package는 통과하지만 company-document enrichment 등 비핵심 영역에 외부 URL/공개성 문제 또는 추가 evidence review가 남는다.

FAIL:
- 새 parser/collector 예외/기업별 hard-code가 필요하다.
- 또는 잘못된 company/site/legal-entity continuity를 자동 확정한다.
- 또는 일반 workflow 운영 예산을 기업 규모 때문에 반복적으로 초과한다.

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

### POSCO — G1 FAIL (temporal legal-entity boundary)
- 평가 Run: `33232906478` (#131)
- Commit: `826eb5ae86ccda8794c26470df54796483bf9c38`
- 요청 scope: 포항제철소 + 광양제철소
- Discovery evidence: 현 `주식회사 포스코` active period를 2022~로 기록하고, 2022-03-01 물적분할 전 자료는 자동 승계하지 말 것을 명시함.
- 신규 parser/collector 수정 없이 ICIS attempt 1 통과:
  - PRTR `DATA_FOUND`: 71 rows, detail 71/71, detail table 1,878 rows, errors 0
  - Chemical Statistics `DATA_FOUND`: 93 rows, 43 unique business-site IDs, detail 93/93, detail table 7,635 rows, errors 0
  - ICIS gate `PASS`; retry/replay 불필요
- 그러나 raw evidence에서 포항/광양 핵심 source ID가 2020~2024에 걸쳐 이어짐.
- `company_profile_builder.py`는 current legal name alias에 `year_start=2022`를 보존하지만, `postprocess.py`의 identity resolution은 source candidate의 관측연도만 `valid_from/valid_to`로 사용하고 legal-entity active period를 적용하지 않음.
- `requested_scope.py` 역시 canonical/source ID를 기준으로 analysis scope를 선택하며 legal-entity 연도 경계를 적용하지 않음.
- 따라서 분할 전 2020~2021 source rows가 현 사업회사 포항/광양 canonical scope에 들어갈 수 있음.
- 이는 `REVIEW_REQUIRED`만으로 충분한 문제가 아니라 **알려진 법인경계를 무시한 자동 continuity 위험**이므로 G1 FAIL.
- ENV-INFO 수집은 코드 수정 없이 완료했으나 attachment recovery가 장시간 실행되어 운영성(performance) 평가는 Run 종료 후 추가 기록 예정.

## 4. Intervention Ledger

| 최초 발견 기업/상황 | 문제 유형 | 당시 조치 | 기업 전용 조치인가 | 이후 재사용 상태 |
|---|---|---|---|---|
| Hanwha Aerospace | ENV-INFO zero-result 뒤 stale DOM row를 결과로 오인 | explicit zero-result가 stale DOM보다 우선하도록 수집 검증 강화 | 아니오 | 일반 규칙으로 유지 |
| Kumho Petrochemical | ENV-INFO 중복 첨부가 500 MiB logical budget을 소진하여 후속 첨부를 `DOWNLOAD_FAILED`로 오분류 | SHA dedup + unique-byte budget + recovery + budget skip 상태 분리 | 아니오 | Hyundai에서 수정 없이 재사용 성공 |
| ICIS outage | PRTR/Chem Stats 외부 호스트 timeout | 3회 retry 후 exact query fingerprint가 맞는 최근 성공본만 provenance replay | 아니오 | fresh/replay 두 경로 실데이터 QA 통과 |
| Kumho Petrochemical | K-BREF/회사문서 외부 저장소 timeout·catalog-only | 공식 source 우선, direct PDF 검증, unavailable/review 상태 유지 | 아니오 | source-availability 규칙으로 유지 |
| Kumho Petrochemical semantic QA | 같은 AIR/WATER 대분류라는 이유로 서로 다른 세부 이슈를 FOUR_LAYER_READY로 연결 | semantic bridge gate; 세부 pollutant/issue 연결 요구 | 아니오 | 회귀테스트에 고정 |
| Hyundai Motor #127 | 새로운 완성차 기업 | **코드 수정 없음** | 해당 없음 | G1 PARTIAL PASS |
| POSCO #131 | 2022 물적분할 전후 동일 site/source ID의 legal-entity continuity | 테스트 중 수정 금지. 범용 temporal identity gate 필요성을 발견 | 아니오 — 분사/합병/물적분할 기업 공통 | **G1 FAIL; generic defect로 등록** |

## 5. POSCO가 드러낸 새 범용 결함

### `TEMPORAL_LEGAL_ENTITY_BOUNDARY`

현재 시스템은 다음 둘을 충분히 분리하지 않는다.

1. **physical/site continuity**: 같은 제철소·주소·source-native facility ID가 여러 해 이어지는가.
2. **legal-entity continuity**: 그 해의 환경자료를 현재 요청한 법인의 자료로 귀속해도 되는가.

포스코 사례에서는 site continuity가 있어도 2022-03-01 전후 법인이 동일하지 않다. 따라서 site continuity만으로 current-company continuity를 만들면 안 된다.

### 다음 수정의 범용 요구사항

테스트 종료 후에만 수정한다.

- raw collector evidence는 그대로 보존한다.
- source identity는 site match와 legal-entity temporal applicability를 별도 필드/판정으로 가진다.
- 현재 법인의 `active_period` 이전 row는 current-company analysis에서 자동 제외하거나 `TEMPORAL_ENTITY_REVIEW`로 보류한다.
- predecessor→current continuity가 공식적으로 별도 확인된 경우에만 명시적 evidence link를 통해 연결한다.
- 물리적 사업장 연속성과 법적 법인 연속성은 별도 관계로 기록한다.
- requested scope filtering은 source ID만 보지 말고 row year와 entity-validity를 함께 검사한다.
- 회귀테스트에는 최소한 다음을 포함한다.
  1. 2022 신설 법인 + 동일 source ID의 2020/2021/2022/2023 rows
  2. 2020/2021 raw 보존
  3. current-company analysis에서는 2020/2021 자동 제외/보류
  4. 2022+ rows 정상 포함
  5. explicit predecessor continuity evidence가 없으면 자동 merge 금지

## 6. 현재 범용성 판단

현재까지 확인된 것은 다음과 같다.

- **collector/parser portability**는 강해지고 있다. Hyundai와 POSCO 모두 새 collector/parser 없이 core public-source 수집이 진행됐다.
- 과거 기업에서 만든 generic recovery/retry/fail-closed 규칙이 다른 기업에서 재사용되는 사례도 확인됐다.
- 반면 **corporate restructuring의 시간축 identity**는 아직 generalization gap이다.
- 따라서 현재 프로젝트를 `회사명만 넣으면 항상 완전 자동으로 정확한 장기시계열을 만드는 universal zero-touch system`이라고 부르면 과장이다.
- 더 정확한 현재 정의는 **공식 공개 환경자료 수집·검증의 반복 작업을 자동화하고, 법인/사업장/근거의 불확실성을 명시적으로 사람이 검토할 수 있게 만드는 AI-assisted environmental research framework**이다.

다음 blind test는 `TEMPORAL_LEGAL_ENTITY_BOUNDARY`를 일반 규칙으로 수정하고 기존 회사 회귀테스트를 통과한 뒤 실시한다.
