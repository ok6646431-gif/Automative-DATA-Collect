# APPLICATION_EVIDENCE

> 목적: SK하이닉스 지원서의 **AI 기반 문제해결 경험** 문항에서 사용할 수 있는 사실·실행기록·정량 evidence를 분리해 기록한다.  
> 이 문서는 자소서 문장 초안이 아니다. 확인할 수 없는 값은 추정하지 않는다.  
> 기준 브랜치: `run/control-plane`  
> 기준일: 2026-08-26  
> SK하이닉스 최종 QA 실행: GitHub Actions Run `32910781013` (#102), commit `a1d888e01caa9bd7fd512542a3ac7baad2cba50d`

## 0. 먼저 구분해야 하는 사실

이 프로젝트는 두 단계로 구분된다.

- **A. 자료 확보·정리층**: 기업/사업장을 식별하고 ENV-INFO, PRTR, 화학물질통계, CleanSYS, SOOSIRO, 회사 공식문서 등을 수집·검증해 사용자가 원하는 폴더 구조의 Human Archive로 제공한다.
- **B. 학습주제 선별층**: 기업 환경관리를 자동 평가하는 것이 아니라, 많은 자료 중 **사람이 더 공부할 가치가 있는 변화와 관련 근거를 좁혀 주는 것**이 목적이다.

현재 지원서 evidence에서 가장 중요한 변화는 B단계의 판단범위를 다음과 같이 제한한 것이다.

1. 큰 값·큰 변화만으로 환경 중요도/위험도를 정하지 않는다.
2. 시계열 변화(`OBSERVED`), 회사 관리활동(`COMPANY_ACTION`), 업종 기술근거(`INDUSTRY_TECHNICAL`), 회사 향후방향(`FUTURE_DIRECTION`)을 서로 독립된 근거층으로 유지한다.
3. 근거가 같은 시기에 존재해도 인과를 자동 확정하지 않는다.
4. 생산량·유량·공정조건·허가조건·산정경계 등이 없으면 성과·원인·법적 준수를 판단하지 않고 질문으로 남긴다.
5. 원자료와 source locator를 유지하여 사람이 다시 확인할 수 있게 한다.

---

# A. 변경 전과 변경 후 비교

## A-1. '진짜 초기의 큰 값/큰 변화 중심 방식'의 정확한 후보 수

**확인 불가.**

현재 GitHub에 보존된 가장 이른 정형 `review_selection` 실행 시점에는 이미 다음 경계조건이 들어가 있었다.

- short series를 장기추세로 해석 금지
- 측정정의가 바뀐 지표를 임의 연결 금지
- PRTR 수량을 hazard/risk로 해석 금지
- 유입부하 없이 처리효율 판단 금지
- 적용기준 없이 법적 준수 판단 금지
- 투자와 지표 변화의 시간적 중첩만으로 인과 판단 금지

따라서 **'초기에는 N개를 단순 큰 변화로 뽑았고 현재는 M개가 됐다'는 숫자를 소급해서 만들면 안 된다.**

## A-2. 복원 가능한 최초 정형 후보선별 실행 — 삼성전자 DS Run #85

Run: `32847857228`  
Commit: `43c29d09151339625616283efe922df84d6e2e7c`  
Title: `Run Samsung DS scoped review selection integration`

실제 결과:

- 원 환경 metric rows: **1,352**
- metric series: **319**
- DS 요청범위 metric series/signals: **148**
- 관리활동: 전체 **187**, DS 범위 **100**
- PRTR chemical rows: 전체 **461**, DS 범위 **404**
- 화학물질통계 substance rows: 전체 **2,389**, DS 범위 **1,371**
- chemical candidates: **28**
- topic candidates: **31**
- 초기 규칙의 `DEEP_DIVE_CANDIDATE`: **4**

즉 복원 가능한 최초 정형 funnel은:

**DS 지표 148개 → 검토주제 31개 → 초기 상세검토 4개**

다만 이 실행은 이미 위 경계조건을 포함했으므로 '단순 큰 값 방식'이라고 표현하면 안 된다.

## A-3. 독립 근거층·문서 페이지 검증 추가 후 — 삼성전자 DS Run #89

Run: `32855276091`  
Commit: `9b463ef2e13c58303e8ee7cac7ebfa01e67d4774`  
Title: `Run Samsung DS tightened cross-layer review`

동일한 31개 topic candidate를 4개 독립 근거층으로 다시 검토한 결과:

- review candidates: **31**
- `FOUR_LAYER_READY`: **23**
- `MULTI_LAYER_REVIEW`: **8**
- Evidence layer rows: **2,718**
  - OBSERVED 91
  - COMPANY_ACTION 390
  - INDUSTRY_TECHNICAL 2,050
  - FUTURE_DIRECTION 187
- 분석 공식문서: **11개**
- 페이지 스캔: **1,338 pages**
- semantic candidates: **2,494**
- document semantic failures: **0**

중요: 새 기준은 단순히 후보 수를 줄이는 필터가 아니다.  
**후보가 왜 볼 만한지 근거층을 분리하고, 어느 후보가 근거가 부족한지를 명시하는 절차**다.

## A-4. 현재 기준의 SK하이닉스 최종 실행 — Run #102

Run: `32910781013`

실제 funnel:

- 환경 metric rows: **365**
- metric series: **86**
- 요청범위 metric series/signals: **66**
- 관리활동: **41** (요청범위 41)
- PRTR chemical rows: **157** (요청범위 157)
- Chem Stats substance rows: **29**, 현재 요청 사업장에 canonical 확정된 행 **0**
- chemical candidates: **21**
- topic candidates: **16**
- 형식적 `FOUR_LAYER_READY`: **10**
- `MULTI_LAYER_REVIEW`: **6**
- open study questions: **22**
- 최종 보고서 상세검토 records: **10**

현재 funnel:

**요청범위 지표 66개 → 검토주제 16개 → 4개 근거층 충족 10개 / 근거 부족 보류 6개**

### '큰 변화가 보여도 승격하지 않은' 실제 사례

#### 사례 A: 청주3공장 대기 NOx

CleanSYS signal:
- 2021: 0 kg
- 2022: 4,707 kg
- 2023: 7,622 kg
- 2024: 36,913 kg
- 2025: 42,446 kg
- Signal: `DIRECTIONAL_UP | LEVEL_SHIFT_CANDIDATE`

그러나 최종 상태:
- OBSERVED: 있음
- COMPANY_ACTION: **0**
- INDUSTRY_TECHNICAL: 있음
- FUTURE_DIRECTION: 있음
- 결과: **`MULTI_LAYER_REVIEW` 유지**

즉 큰 증가 Signal만으로 상세검토 주제로 승격하지 않았다.

추가 주의: 2021의 `0`이 실제 무배출인지 신규 TMS/공개 시작점인지 아직 확정되지 않았다. 따라서 향후 `ZERO_SEMANTICS_REVIEW` 성격의 검증을 보완할 필요가 있다.

#### 사례 B: 이천 스마트에너지센터 대기 NOx

CleanSYS signal:
- 2022: 0 kg
- 2023: 94,608 kg
- 2024: 131,995 kg
- 2025: 145,455 kg
- Signal: `DIRECTIONAL_UP | LEVEL_SHIFT_CANDIDATE`

그러나:
- COMPANY_ACTION layer: **0**
- 결과: **`MULTI_LAYER_REVIEW`**

큰 변화가 있다는 이유만으로 '중요 환경문제'나 '관리 악화'로 승격하지 않았다.

---

# B. SK하이닉스 최종 후보 품질 검증

## B-1. 시스템 형식상 최종 상세검토 후보

Run #102 기준 `FOUR_LAYER_READY` record는 **10개**다.

모든 10개 record에 대해:
- 연결된 evidence ID는 Registry에 존재
- 연결 evidence의 `source_locator` 누락 **0건**
- INDUSTRY_TECHNICAL/FUTURE_DIRECTION에는 page-grounded locator(`#page=`)가 최소 1개 이상 존재

따라서 **원문 locator까지의 traceability 자체는 10/10**이다.

그러나 'trace 가능'과 '근거가 의미상 적절함'은 다르다. 아래 수동 semantic QA에서 두 개의 약한 연결과 하나의 Identity 조건부 record를 발견했다.

| # | 사업장/영역 | 관찰된 변화 | 회사 관리활동 근거 | 기술근거/미래방향 | trace | 공개자료만으로 보류해야 할 판단 | 현재 QA |
|---|---|---|---|---|---|---|---|
| 1 | 청주사업장 AIR | NOx 341.710→313.122→120.061→107.385→197.462 t; SOx 4.772→13.981 t | De-NOx 투자, NOx TMS, NH3 방지시설 개선, 저NOx 버너 등 | 반도체 K-BREF p.92/p.207 등; 2024 지속가능경영보고서 page locator | 가능 | 생산량·배출가스량·가동시간·배출원 구성 없이는 원인/성과 판단 불가 | **강함** |
| 2 | 청주사업장 CHEMICALS | 화학물질 배출총량 91.0→100.47→39.16→24.87→46.49 | 현재 cross-layer의 유일 action이 **M15X DRAM 생산기반 투자**로 연결됨 | K-BREF p.31/p.92~93; 지속가능경영보고서 화학물질 관리 page | 가능 | 물질별 공정경로·취급량·유해성·사업장 관계 필요 | **약함: action semantic mismatch. 형식적 READY를 그대로 최종검증으로 쓰면 안 됨** |
| 3 | 청주사업장 GHG/ENERGY | Scope1 127,526(2023)→1,190,897(2024); Scope2 1,615,852→691,690; 총량 1,743,378→1,882,587 | 2024 Smart Energy Center 가스복합 열병합 자가발전, 태양광; 냉각수 폐열회수 등 | K-BREF energy management; RE100/Net Zero 보고서 pages | 가능 | 자가발전의 Scope1/2 재분류, 생산량, 전력구성·산정경계 없이는 성과/원인 판단 불가 | **강함** |
| 4 | 청주사업장 WATER | SS 79.68→25.30; T-N 580→271.43; TOC series 정의/0 이슈 존재 | 2022 고농도 T-N 처리계통 변경·인산공급·암모니아 탈기탑, 2023 drain 계통 변경 | K-BREF 폐수 배출·처리 흐름 p.17/p.92; 2023 보고서 p.52/p.104 | 가능 | 유입농도·유량·부하·가동조건 없이는 처리효율/인과 판단 불가 | **강함** |
| 5 | 청주사업장 WATER_RESOURCES | 재이용수 7.92M→14.61M; 용수사용 27.40M→40.89M | 현재 cross-layer의 유일 action이 **M15X 일반 생산투자** | K-BREF 초순수/용수 p.92~93; 2023 보고서 p.24/p.49/p.51~52 | 가능 | 생산규모·재이용 용도·취수원·공정수요 필요 | **약함: 직접 수자원 action이 아닌 일반 생산투자를 action으로 사용** |
| 6 | 청주1공장 AIR | CleanSYS NOx 2022 0→2023 1,815→2024 1,782→2025 1,519 kg | 청주사업장 De-NOx/TMS 등 | K-BREF + 회사 문서 page | 가능 | CleanSYS 주소가 없어 Source Identity가 `NAME_ONLY_CANDIDATE`; 시작점 0 의미도 확인 필요 | **조건부: broader 청주 AIR와 topic_id 중복, identity REVIEW_REQUIRED** |
| 7 | 이천본사 AIR | NOx 363.530→158.255→289.317; SOx 6.812→31.808 t | NOx 저감 Infra, De-NOx, HF/HCl TMS 등 | K-BREF air emission context p.92/p.207 등 | 가능 | 생산/유량/신규 배출원·운전조건 없이는 반등 원인 판단 불가 | **강함** |
| 8 | 이천본사 GHG/ENERGY | Scope1 194,671→1,511,796; Scope2 2,476,290→1,440,785 | Chiller ECO mode, vacuum/pump 효율화 등 | K-BREF energy p.22/p.27; RE100/Net Zero pages | 가능 | 생산량, 전력/연료 구성, 산정경계 변경 확인 필요 | **강함** |
| 9 | 이천본사 WATER | SS 34.16→14.78; T-P 0.64→0.09 | 폐수 생물감시장치, 재이용시스템, WWTP 관련 개선 등 | K-BREF wastewater p.17/p.92; 2023 report p.52/p.104 | 가능 | 유입부하·유량·적용기준·운전조건 필요 | **강함** |
| 10 | 이천본사 WATER_RESOURCES | 재이용 19.01M→37.67M; 용수사용 약 38.60M→38.51M (중간 변동) | Blow-down/Drain 재이용, W12B 재이용시스템, Scrubber 세정수 재사용 | K-BREF water-use p.92~93; 2023 report p.49/p.51~52 | 가능 | 생산량·재이용수 용도·취수경계 없이는 효율성 평가 불가 | **강함** |

### B-2. 현재 시점에서 지원서에 사용 가능한 보수적 해석

- 시스템의 형식적 `FOUR_LAYER_READY`: **10**
- 원문 source locator 추적 가능: **10/10**
- 위 수동 semantic audit에서 직접적인 관리활동 연결이 충분한 record: **7**
- action semantic linkage가 약해 downgrade가 필요한 record: **2** (청주 CHEMICALS, 청주 WATER_RESOURCES)
- Source Identity가 아직 name-only이고 broader topic과 중복되는 conditional record: **1** (청주1공장 AIR)

따라서 지원서에서는 **'최종 10개를 모두 검증했다'고 쓰는 것은 부적절**하다.

안전한 표현을 뒷받침하는 사실은:
- 시스템은 16개 후보 중 10개를 형식적 four-layer ready로 좁혔다.
- 그 10개를 다시 원문/semantic 관점에서 확인하자 2개는 연결 의미가 약하고 1개는 identity가 조건부임을 확인했다.
- 즉 **원자료 추적 가능성은 확보했지만 semantic 최종승인은 사람 검토 단계로 남아 있다.**

이 자체가 현재 플랫폼이 '완성된 자동평가 시스템'이 아니라 '검토 범위를 좁히는 시스템'이라는 증거다.

---

# C. 새 기준이 기존 단순 신호 방식보다 나았다는 실제 사례

## C-1. 가장 명확한 '큰 변화지만 보류' 사례 — 청주3공장 NOx

- 2023: 7,622 kg
- 2024: 36,913 kg
- 증가량: 29,291 kg, 약 **+384%**
- 2025: 42,446 kg
- 자동 Signal: `DIRECTIONAL_UP | LEVEL_SHIFT_CANDIDATE`
- 그러나 해당 source-site record에 같은 사업장/영역의 COMPANY_ACTION evidence가 0
- 결과: `MULTI_LAYER_REVIEW`, 상세검토 승격 안 함

**확인된 차이**: 변화폭만 보면 눈에 띄지만, 현재 기준은 다른 근거층이 부족하면 '환경문제/원인'으로 올리지 않는다.

## C-2. 같은 시기의 지표 변화와 투자·시설변화가 있어도 인과를 보류 — 청주 NOx + Smart Energy Center

ENV-INFO 청주 NOx:
- 2023: **107.385 t**
- 2024: **197.462 t**
- 변화: **+90.077 t**, 약 +84%

동시에 2024 ENV-INFO에는 청주 Smart Energy Center 가스복합 열병합 자가발전 및 대기방지시설이 새로 나타난다.

CleanSYS 2024:
- 청주 SEC NOx: **65.974 t**
- 청주3공장 NOx: **36.913 t**
- 2023→2024 CleanSYS 확인 시설 합계 증가규모는 ENV-INFO 전체 증가규모와 유사한 수준이다.

그러나 현재 기준에서는 다음 이유로:
- ENV-INFO와 CleanSYS의 집계경계가 동일하다는 증거 부족
- 생산량·연료사용량·가동시간·배출가스량 부족
- 신규 시설의 운영기간/산정범위 확인 필요

**'SEC 때문에 NOx가 90.077 t 증가했다'고 결론내리지 않는다.**

대신:
> `배출원 구조 변화와 함께 추가 검토할 가치가 있는 주제`

로만 남긴다.

이 사례는 B단계의 목표 변경을 가장 직접적으로 보여준다.

## C-3. Scope 1/2도 같은 원칙 적용

청주:
- Scope1: 2023 127,526 → 2024 1,190,897 tCO2e
- Scope2: 2023 1,615,852 → 2024 691,690 tCO2e
- Total: 2023 1,743,378 → 2024 1,882,587 tCO2e

2024 Smart Energy Center 자가발전과 시간적으로 겹치지만:
- 자가발전에 따른 Scope1/Scope2 회계 이동
- 생산량
- 전력·연료 구성
- 산정경계

를 확인하지 않고는 성과/원인을 판단하지 않는다.

**지원서에서 '투자 후 배출이 개선/악화됐다'는 문장 근거로 사용하면 안 된다.**

---

# D. Human-AI 역할 구분

| 단계 | 현재 수행 주체/방식 | 실제 내용 | 사람이 남는 이유 |
|---|---|---|---|
| 공개자료 탐색·수집 | AI agent + collector 자동화 | 연도/회사 검색, 상세자료·첨부 수집, raw 보존 | 반복 작업이므로 자동화 대상 |
| 기술적 수집 성공 검증 | 규칙 | request 성공, row/detail/attachment 상태, zero-result 처리, scope request_id 확인 | HTTP 성공 자체를 evidence 성공으로 보지 않기 위해 fail-closed |
| 회사/사업장 Identity | 규칙 + REVIEW_REQUIRED | 공식주소 exact match, cross-source match, related entity exclusion | 주소 없음/분사/유틸리티 등은 공개자료만으로 동일 사업장 확정이 부적절 |
| 다년도 지표 Signal | 규칙 | DIRECTIONAL_UP/DOWN, LEVEL_SHIFT, SHORT_SERIES 등 | Signal은 '볼 만함'이지 위험/성과 판정이 아님 |
| 문서 의미추출 | AI/규칙 | 공식문서 페이지 단위 candidate evidence 추출 | 문서 존재가 회사의 BAT 적용 또는 성과를 뜻하지 않음 |
| 4개 evidence layer 연결 | 규칙 | OBSERVED / COMPANY_ACTION / INDUSTRY_TECHNICAL / FUTURE_DIRECTION | 시간적·주제적 중첩을 인과로 바꾸지 않음 |
| 최종 semantic 적합성 확인 | **사람 검토로 유지** | action이 정말 해당 환경주제와 직접 관련 있는지, source site가 동일한지 확인 | 현재 Run #102에서도 M15X 일반투자가 화학/수자원 action으로 연결되는 오연결을 발견함 |
| 원인·성과·준수 판단 | **자동 확정 금지** | 생산량·유량·공정조건·허가조건 등이 있을 때만 별도 검토 | 공개자료만으로 결론내리는 것이 부적절하기 때문 |

핵심은 **'AI가 못해서 사람이 한다'가 아니라, 공개근거의 범위를 넘어서는 판단을 시스템이 하지 않도록 사람이 승인경계를 맡는다**는 것이다.

---

# E. 정량적 결과

## E-1. 현재 SK하이닉스 Run #102

| 항목 | 실제값 |
|---|---:|
| 요청 사업장 | 공식 생산거점 주소 기준 **5개** (이천 1, 청주 4) |
| 요청기간 | **2020~2026**; 실제 환경실적 Source별 공개연도는 다름 |
| ENV-INFO | 2020~2024, discovery 15 rows, detail 15/15, attachment 110/110 |
| PRTR | 2020~2024, discovery 19 rows, detail 19/19, detail table 504 rows |
| 화학물질통계 | 2022/2024, discovery 3 rows, detail table 102 rows; requested canonical site 확정 substance rows 0 |
| CleanSYS | 2020~2025, 6 candidates, annual 26 rows |
| SOOSIRO | 2020~2025, annual 18 rows + 2024 daily 1,098 rows |
| requested-scope metric series | **66** |
| raw metric rows | **365** |
| 관리활동 | **41** |
| PRTR chemical rows | **157** |
| chemical candidates | **21** |
| 공식문서 다운로드 | **12개** |
| 문서 semantic 분석 | **8개 / 1,035 pages** |
| 문서 semantic candidates | **2,364** |
| document semantics failure | **0** |
| Evidence layer rows | **2,496** |
| 초기 topic candidates | **16** |
| formal FOUR_LAYER_READY | **10** |
| MULTI_LAYER_REVIEW 보류 | **6** |
| report detailed records | **10** |
| source locator 추적 가능한 formal ready | **10/10** |
| 현재 수동 QA상 바로 사용하기 강한 records | **7** |
| semantic-link downgrade 필요 | **2** |
| identity-conditional/중복 record | **1** |
| Validation Queue | **14** |
| Human Archive | `COMPLETE`, user files 129, system files 309, archive files 446 |

## E-2. 삼성전자 DS — 현재 B workflow 교차검증

요청범위:
- 기흥, 화성, 평택, 천안, 온양 **5개 canonical sites**
- ENV-INFO/PRTR 2020~2024
- Chem Stats 2020/2022/2024
- CleanSYS/SOOSIRO 2020~2025

Run #85:
- DS metric series 148
- topic candidates 31
- early deep dive 4

Run #89:
- 동일 topic candidates 31
- FOUR_LAYER_READY 23
- MULTI_LAYER_REVIEW 8
- 문서 11개, 1,338 pages
- semantic candidates 2,494
- semantic failures 0

## E-3. 적용 기업 수는 정의를 나눠야 함

**현재의 B단계(`review_selection + page-grounded document semantics + cross_layer_review`)를 end-to-end 실행해 확인한 기업: 2개**
1. 삼성전자 DS
2. SK하이닉스 국내 생산사업장

**A단계/control-plane 및 cross-company 검증 기록까지 포함하면 추가 사례가 존재**
- LG에너지솔루션 Run #70 (`32239679271`): 수집·Human Archive까지 PASS. 분사 이력 때문에 site identity는 의도적으로 REVIEW_REQUIRED 상태로 남김.
- 한화에어로스페이스: Source별 cross-company 검증 과정에서 ENV-INFO stale DOM false-positive 문제 발견.

따라서 지원서에서 단순히 '4개 기업 완전 적용'이라고 쓰는 것은 부정확하다.  
안전한 정량 표현은:
- **현재 분석 B workflow end-to-end 검증: 2개 기업, 10개 requested canonical sites**
- **추가로 분사기업·복잡기업을 A단계/cross-company 검증 사례로 사용**

## E-4. 시간절감률·정확도

**측정하지 않음. 사용 금지.**

- 시간 절감률: 확인 불가
- 정확도 %: 확인 불가
- 개선율 %: 확인 불가

---

# F. SK하이닉스 적용 상태

## F-1. 사업장/범위

공식 requested scope:
- 이천캠퍼스(본사): 경기도 이천시 부발읍 경충대로 2091
- 청주캠퍼스(대신로): 충북 청주시 흥덕구 대신로 215
- 청주캠퍼스(2순환로): 충북 청주시 흥덕구 2순환로 959
- 청주캠퍼스(직지대로): 충북 청주시 흥덕구 직지대로 337
- 청주캠퍼스(에스케이로): 충북 청주시 흥덕구 에스케이로 120

요청기간은 2020~2026이지만 Source의 실제 공개주기는 다르므로 2025/2026 값을 임의 생성하지 않는다.

## F-2. 확보 Source

- ENV-INFO
- PRTR
- 화학물질통계
- CleanSYS
- SOOSIRO
- SK하이닉스 지속가능경영보고서/환경정책/공식 뉴스
- 반도체 제조업 K-BREF
- 공식 Scope 3 가이드 등

## F-3. 공개자료만으로 아직 판단할 수 없는 부분

1. Smart Energy Center와 공식 캠퍼스 간 환경관리/법적 사업장 관계
   - 화학물질통계에는 `에스케이로 65`, `청주스마트에너지센터` 등 별도 주소가 나타남.
   - 같은 회사/인접 위치라는 이유로 본 Fab data에 자동합산하지 않음.
2. CleanSYS 시작연도 0의 의미
   - 실제 zero인지 신규 시설/TMS 공개시작인지 확인 필요.
3. 생산량·공정 가동률·유량·배출가스량
   - 연간 환경지표 변화 원인의 핵심 denominator가 공개자료에 부족함.
4. 개별 시설의 적용 허가조건/법적 배출기준
   - 회사 공개값만으로 compliance 판단 금지.
5. 현재 cross-layer semantic linkage 품질
   - Run #102에서 M15X 일반 생산투자가 화학물질/수자원 company-action 근거로 연결된 2건 확인.
   - 향후 동일 영역 action relevance 검증 강화 필요.

이 항목들은 '실패를 숨긴 상태'가 아니라 **현재 사람 검토로 남긴 보완대상**이다.

---

# G. 판단이 실제 작업방식에 반영됐다는 근거

## G-1. 한화에어로스페이스 ENV-INFO stale result 사례

프로젝트 검증 기록상:
- targeted fallback 실행이 기술적으로 성공
- `result_rows=45`
- 그러나 실제 화면/bodyText에는 **`검색결과 0건`**
- 45행은 한국지엠·롯데정밀화학·삼성전자 등 이전/초기 DOM의 stale list
- 해당 45행 전부 폐기

이 사건 이후의 설계원칙:
- HTTP/selector success ≠ valid evidence
- zero-result를 명시적으로 처리
- raw를 보존
- identity/scope가 확정되지 않은 결과는 분석에 자동 투입하지 않고 REVIEW_REQUIRED
- stale/mismatched request evidence는 fail-closed

**주의:** 이번 APPLICATION_EVIDENCE 작성 과정에서 당시 `output(3).zip` 원본을 다시 회수하지는 못했다. 위 45행은 2026-08-18 당시 수동 재검증 기록에 근거한다. 지원서에서 숫자를 사용할 경우 당시 검증기록을 evidence origin으로 명시하는 것이 안전하다.

## G-2. stale request evidence를 현재 시스템이 실제 거부하는 동작

SK하이닉스 초기 실행에서 corporate-document request가 삼성전자 DS request_id로 남아 있었을 때:
- documents declared 16
- downloaded 0
- skipped 16
- status `INVALID_SCOPE`

즉 시스템은 다른 회사 공식문서를 SK하이닉스 근거로 섞지 않고 거부했다.

SK하이닉스 문서 request를 올바르게 교체한 Run #102에서는:
- official docs downloaded 12
- semantic analysis 8 docs / 1,035 pages

이는 **scope mismatch 시 fail-closed하는 규칙이 실제 결과물 오염을 막았고, 올바른 입력으로 수정 후 분석층이 회복된 사례**다.

---

# H. 지원서에서 사용하기 가장 강한 실제 사례 2개

## 추천 1 — 한화에어로 stale DOM 45행 폐기 → 검증규칙 변경

**왜 강한가**
- AI/자동수집이 '성공'으로 보고한 결과를 사용자가 실제 Source와 대조했다.
- 단순히 45행을 다시 수집해 달라고 한 것이 아니라, **기술적 성공과 유효 evidence를 분리하는 규칙**으로 바꿨다.
- 이후 scope/identity/zero-result/REVIEW_REQUIRED/fail-closed 구조로 연결된다.

**지원서에서 증명 가능한 핵심**
- 자동수집 결과 45행
- 실제 화면 `검색결과 0건`
- 45행 폐기
- 이후 검증규칙 구조화

**주의**
- 현재 이 문서 작성 시 원 ZIP 재회수는 하지 못함. 당시 수동검증 기록 기준.

## 추천 2 — '변화+투자=원인' 해석을 버리고 근거층/판단보류 구조로 변경

**가장 보여주기 좋은 현재 실증: SK하이닉스 청주 NOx / Smart Energy Center**

- ENV-INFO NOx: 107.385 t(2023) → 197.462 t(2024)
- 같은 시기 SEC 가스복합 자가발전/대기방지시설 등장
- CleanSYS에서 2024 SEC NOx 65.974 t
- 겉보기에는 원인을 연결하기 쉬움
- 하지만 집계경계·생산량·연료·가동시간·배출가스량이 부족해 인과를 자동 확정하지 않음
- 결과는 '관리 악화'나 'SEC가 원인'이 아니라 **추가 검토 주제**로 유지

**왜 강한가**
- 사용자의 판단이 AI의 목표 자체를 '자동평가'에서 '추가 검토 범위 축소'로 바꾼 것을 설명하기 좋다.
- 현재 Run #102 artifact에서 실제 수치·관리활동·K-BREF·회사방향·제한조건을 모두 trace할 수 있다.
- 지원 회사인 SK하이닉스에 동일 workflow를 그대로 적용한 결과이므로 별도 맞춤 기준을 만들었다는 오해가 적다.

---

# I. 아직 완성되지 않은 부분 — 면접 전 보완 계획으로만 사용 가능

지원서에서 '완성했다'고 단정하면 안 되는 부분:

1. **Site Relationship layer**
   - 본공장/캠퍼스와 Smart Energy Center·유틸리티·별도 처리시설 관계를 별도 relation으로 모델링할 필요.
2. **Zero semantics**
   - TMS 시계열 첫 연도 `0`을 실제 0과 신규등록/공개시작으로 구분.
3. **Semantic relevance gate**
   - '같은 회사/기간의 투자'가 해당 환경주제의 직접 관리활동인지 추가 검증.
   - 현재 Run #102에서 2건의 weak action linkage를 확인함.
4. **최종 human approval state**
   - 현재 four-layer ready와 human-approved study topic을 별도 상태로 분리하는 개선 여지.

이들은 2026-08-26 지원서 제출 시점에 **향후 보완 예정**이라고 표현할 수 있는 실제 미완료 항목이다.

---

# J. 최종 비교표

| 항목 | 초기 방식 | 현재 방식 | 실제 확인된 차이 |
|---|---|---|---|
| AI의 목표 | 많은 데이터를 모으고 변화 후보를 찾는 데 초점 | 사람이 추가 검토할 학습주제와 근거를 좁힘 | 자동평가/원인확정이 아니라 evidence-backed review 후보 생성으로 목표를 제한 |
| 후보 선정 기준 | 복원 가능한 최초 정형 버전은 Signal + 일부 same-site action; 그 이전 단순 큰 값 방식의 정확한 규칙/후보수는 확인 불가 | OBSERVED + COMPANY_ACTION + INDUSTRY_TECHNICAL + FUTURE_DIRECTION의 독립 근거층 | SKH 16 후보 → 10 formal ready / 6 hold |
| 사람의 개입 지점 | 개별 오류 발견 후 재확인 중심 | unresolved identity, semantic relevance, causal/performance/legal conclusion을 의도적으로 승인대상으로 남김 | Run #102 formal ready 10 중 semantic weak 2 + identity conditional 1을 추가로 식별 |
| 후보 수 | '진짜 초기 큰 변화 방식' 정확한 수 확인 불가. 최초 복원 가능한 Samsung Run #85: 31 topics / early deep dive 4 | Samsung Run #89: 31 → 23 ready/8 hold; SKH Run #102: 16 → 10 ready/6 hold | 새 절차는 단순 축소가 아니라 readiness와 부족근거를 분리 |
| 근거 검증 방식 | metric/action 중심 | 원자료 locator + 공식문서 page-grounded semantics + 4 layer registry | SKH formal ready 10/10 locator trace 가능; docs 8/1,035 pages, semantic failure 0 |
| 판단 보류 조건 | 개별적으로 확인 | short series, 정의변경, identity 불확실, PRTR risk 오해, inlet/load 부재, permit 기준 부재, temporal overlap만 존재 등 명시적 rule | 청주3 NOx는 큰 증가에도 company action 근거 0 → MULTI_LAYER_REVIEW; SEC/NOx는 동시기라도 인과 보류 |

---

# K. 지원서 작성 시 사용하면 안 되는 주장

- `시간을 XX% 절감했다` → 측정 안 함
- `정확도가 XX% 향상됐다` → 측정 안 함
- `AI가 환경리스크를 자동 평가했다` → 현재 목표와 반대
- `10개 최종 주제를 모두 검증 완료했다` → formal ready 10일 뿐 semantic/identity QA 이슈 존재
- `SEC가 청주 NOx 증가의 원인이다` → 확인 안 됨
- `투자 때문에 환경성과가 개선됐다` → 인과 확인 안 됨
- `BAT 문서가 있으므로 SK하이닉스가 해당 BAT를 적용한다` → 확인 안 됨
- `화학물질통계가 없다` → 틀림. 데이터는 있으나 현재 공식 캠퍼스 canonical site와 관계가 미확정
