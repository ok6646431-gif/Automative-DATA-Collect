# 기업 실데이터 기반 환경관리 학습 시스템 v1.2

> `LEARNING_SYSTEM_V1.md`의 목적·기본 카드 구조를 유지하면서, 첫 실제 학습자 테스트에서 발견된 문제를 품질 게이트에 추가한다.

**기준일:** `2026-08-30`

**첫 learner-tested card:** `examples/learning_cards/lotte_yeosu1_nox_v1_3.md`

---

# 1. 유지하는 핵심 원칙

이 시스템의 산출물은 기업 환경자료 요약집이 아니라 **실제 사업장 공개자료를 이용해 환경관리 판단과정을 훈련하는 사례교재**다.

핵심 흐름:

```text
관찰
→ 자료의 정체·경계 확인
→ 질문
→ 공정·발생원리
→ 관리기술
→ 환경관리 업무
→ 법·공식시스템
→ 다시 데이터 해석
→ 아직 모르는 것
→ 원문 근거
```

표시체계는 계속 유지한다.

- `[확인됨]`: 공식·회사 공개자료에서 직접 확인
- `[배경지식]`: 법령·공식 기술자료·BAT 등의 일반 원리
- `[추가확인]`: 현재 근거로 결정할 수 없음

AI는 빈칸을 추정으로 메우지 않는다.

---

# 2. v1.2 신규 필수 게이트

## 2.1 DATA_PRODUCT_BOUNDARY_REQUIRED

서로 다른 자료원에 동일한 사업장·동일 오염물질 이름이 있어도 **같은 데이터 제품이라고 가정하지 않는다.**

비교 전 최소한 다음을 분리한다.

- physical site boundary
- facility / stack boundary
- measurement-system boundary
- reporting / inventory boundary
- time basis
- unit
- measured vs calculated value
- included / excluded sources

### 첫 회귀테스트

롯데케미칼 여수1공장 NOx:

- CleanSYS: 사업장코드 `110019`, TMS 계열 연간 NOx 자료
- ENV-INFO: 같은 여수1공장 NOx 배출실적
- 여수1공장 자체 공개자료: `TMS`와 `기타 배출구` 측정을 동시에 명시
- 공식 ENV-INFO 2024 가이드: 1~3종 사업장은 SEMS 자료를 기준으로 대기오염물질 배출량 작성
- 현행 SEMS 설명: 시설·배출구·운영기록·자가측정·활동도·TMS 자료 등을 관리

따라서 `같은 사업장 = 같은 배출구 집합 = 같은 연간값`으로 처리하면 실패다.

---

## 2.2 DATA_VALIDATION_BEFORE_DOMAIN_EXPLANATION

두 수치가 충돌할 때 바로 공정·방지시설·생산량 원인을 만들지 않는다.

먼저 다음 순서로 데이터 자체를 검증한다.

```text
1. 수집·전사 오류인가?
2. 대상 사업장 identity가 같은가?
3. 비교연도가 같은가?
4. 단위가 같은가?
5. 데이터 정의가 같은가?
6. 포함 시설/배출구가 같은가?
7. 측정·산정 방식이 같은가?
8. 연도 사이 자료경계가 변했는가?
9. 그 다음 공정·운전 원인을 검토
```

학습자가 `값을 잘못 가져온 것 아닌가?`라고 먼저 질문하는 것은 올바른 검증행동으로 취급한다.

---

## 2.3 PRECISION_IS_NOT_COVERAGE

다음 개념을 명시적으로 분리한다.

- measurement frequency / temporal resolution
- measurement precision / reliability
- representativeness
- coverage / completeness

예:

> TMS가 높은 시간해상도의 직접 측정이라는 사실은 TMS 부착 굴뚝에 대한 강점이다. 그러나 그것만으로 사업장 전체 배출량을 더 완전하게 대표한다고 결론낼 수 없다.

`TMS가 실시간이므로 무조건 더 정확한 사업장 총량` 같은 서열화를 금지한다.

---

## 2.4 DATA_RECONCILIATION_MUST_BE_EXPLICIT

서로 다른 자료의 차이를 설명할 때 세 수준을 구분한다.

### LEVEL 1 — boundary difference identified

자료정의·측정경계가 다를 수 있다는 공식 또는 사업장 근거 확보.

### LEVEL 2 — component mapping identified

어느 배출구/시설이 각 자료원에 들어가는지 매핑 확보.

### LEVEL 3 — numerical reconciliation completed

배출구별 수치가 실제로 전체 공개값과 수치적으로 연결됨.

LEVEL 1만 확보하고 `ENV-INFO = TMS + 비TMS 단순합`처럼 LEVEL 3 결론을 내리면 안 된다.

Evidence Ledger에는 `DATA_RECONCILIATION` layer를 사용할 수 있다.

---

## 2.5 HISTORICAL_RULE_TIME_BOUNDARY

현재 또는 후속연도 공식 가이드라인으로 과거연도의 규칙을 자동 소급하지 않는다.

예:

- `2024 ENV-INFO 가이드의 SEMS 우선 규칙` → `VERIFIED / 2024 RULE`
- `2021에도 동일 문구였음` → 2021 가이드 원문을 확보하기 전까지 `NEEDS_EVIDENCE`

법규 freshness뿐 아니라 **행정 가이드·시스템 작성규칙의 연도경계**도 관리한다.

권장 layer:

- `HISTORICAL_RULE`

---

## 2.6 ACTIVE_RETRIEVAL_ANSWER_SEPARATION

기존 `ACTIVE_RETRIEVAL_REQUIRED`를 강화한다.

질문 바로 다음 줄에 정답을 그대로 노출하지 않는다.

허용 방식:

- 프로그램 상 사용자 답변 후 해설 공개
- 웹/Markdown에서는 `<details>` 등 접힌 정답
- 별도 answer key

최소 구성:

- 중간 판단문제 2개 이상
- 데이터 검증 질문 1개 이상
- 새로운 상황의 transfer question 1개
- 답 또는 합격요소는 사용자 응답 전 숨김

목표는 읽으면서 `아 그렇구나`가 아니라 **사용자가 먼저 판단을 생성하도록 하는 것**이다.

---

# 3. 기존 필수 게이트도 계속 적용

v1.1의 다음 규칙은 그대로 유효하다.

- `PROCESS_BRIDGE_REQUIRED`
- `METRIC_DEFINITION_REQUIRED`
- `MASS_BALANCE_THINKING_REQUIRED`
- `MANAGEMENT_VARIABLES_REQUIRED`
- `LEGAL_FRESHNESS_REQUIRED`
- `SOURCE_LOCATOR_REQUIRED`
- `NO_CAUSAL_SHORTCUT`
- `ACTIVE_RETRIEVAL_REQUIRED`
- `EVIDENCE_LEDGER_REQUIRED`

v1.2 신규 규칙은 이를 대체하지 않고 보강한다.

---

# 4. Evidence Ledger v1.2 권장 layer

- `OBSERVED`
- `COMPANY_ACTION`
- `INDUSTRY_TECHNICAL`
- `OFFICIAL_SYSTEM`
- `LEGAL`
- `SITE_PERMIT`
- `DATA_BOUNDARY`
- `DATA_RECONCILIATION`
- `HISTORICAL_RULE`
- `CAUSAL`

특히 다음은 자동 추론 금지:

- `SITE_PERMIT`
- `DATA_RECONCILIATION`
- `HISTORICAL_RULE`
- `CAUSAL`

---

# 5. 첫 카드 학습자 테스트에서 실제로 발견된 것

학습자가 CleanSYS와 ENV-INFO 2021 NOx 차이를 보고 다음 질문을 제기했다.

- 값 수집이 잘못된 것 아닌가?
- 배출량 산정기간이 다른가?
- 산정기준이 다른가?
- 시공간적 범위나 집계방식이 다른가?
- TMS가 실시간이면 더 정확한 것 아닌가?

이 반응을 기준으로 카드 품질을 평가한 결과:

## 작동한 부분

- 수치 차이를 그대로 믿지 않고 원자료 오류 가능성을 먼저 제기함
- 산정기간·범위·집계방식을 독립 변수로 인식함
- 하나의 숫자로 환경성과를 바로 판단하지 않음

## 부족했던 부분

- `같은 사업장`이면 측정범위도 같을 것이라는 직관을 해소할 구조가 부족했음
- TMS의 시간해상도와 사업장 전체 대표성을 구분하는 설명이 부족했음
- 질문 아래 정답이 바로 보여 능동회상이 약해짐

## 실제 추가조사로 해소된 부분

롯데 여수1공장 원문에서 2020·2021년에:

- `T.M.S : 5초 간격 sampling 및 분석결과 전송`
- `기타 배출구 : 오염물질별 별도 측정주기`

가 동시에 확인되었다.

2023·2024에도 TMS와 대기자가측정이 병행됨이 확인되었다.

따라서 `same site ≠ same measurement/data-product boundary`는 더 이상 막연한 주의문이 아니라 **실제 사례근거가 있는 학습내용**이다.

---

# 6. 첫 파일럿 최신 상태

최신 학습자 테스트 반영본:

`examples/learning_cards/lotte_yeosu1_nox_v1_3.md`

상태:

`PUBLISH_READY`

### 확인 완료

- CleanSYS 연간값 원자료 locator
- ENV-INFO 연간값 원문 locator
- 회사 SCR/저NOx Burner/TMS 조치 locator
- CleanSYS와 ENV-INFO 단위
- 여수1공장의 TMS + 기타배출구 병행 공개
- 2024 ENV-INFO SEMS 기준 작성 규칙
- 현행 SEMS 자료관리 범위
- NCC/NOx/저NOx Burner/SCR 기술근거
- 현행 법규 freshness 검증

### 의도적으로 미확정

- 2021 ENV-INFO `1,980.956 ton`의 배출구별 구성
- 2021 CleanSYS와 ENV-INFO의 수치 reconciliation
- 2021 당시 ENV-INFO 가이드의 정확한 SEMS/TMS 문구
- 연도별 TMS 배출구 매핑
- 2023 CleanSYS 급감의 직접 원인
- 여수1공장 개별 통합허가 조건

미확정 사항이 남아 있어도, 그것이 명확히 `NEEDS_EVIDENCE`/`DO_NOT_INFER`로 분리되어 있으면 학습카드는 `PUBLISH_READY`가 될 수 있다.

---

# 7. 다음 자동화 전에 할 일

다음 카드 수를 늘리기 전에 v1.3을 다시 실제 학습자 흐름으로 사용해 본다.

검증 질문:

1. 질문을 보고 정답 노출 전에 실제 판단을 생성하는가?
2. 자료 충돌 시 데이터 검증 → 자료경계 → 공정해석 순서를 자연스럽게 따르는가?
3. `모르는 것`이 답답한 빈칸이 아니라 다음 조사질문으로 기능하는가?
4. 기술지식이 환경관리 업무행위로 번역되는가?
5. 새 사업장·새 오염물질에도 같은 사고순서를 전이할 수 있는가?

이 다섯 가지가 만족된 뒤 카드 생성 자동화 규격으로 고정한다.
