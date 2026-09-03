# Zero-touch Test Company Portfolio

목표는 회사 수를 많이 돌리는 것이 아니라 **서로 다른 기업 구조와 공개자료 구조를 대표하는 테스트군**을 유지하는 것이다.

## Tier 1 — 현재 회귀 기준 기업

| 기업 | 대표 검증 유형 | 현재 역할 |
|---|---|---|
| HD현대삼호 | 동일 법인 사명변경, 행정구역 명칭 변경, company-wide raw와 main-yard scope 분리 | rename/address/scope 기본 회귀 기준 |
| 한화오션 | 대우조선해양 시절 과거자료, stale DART URL, ESG 별도 host, JS PDF, 브로슈어 오분류, 영문 DART 주소↔한글 공공DB 주소, 관계사 한화오션에코텍 | 복합 zero-touch 회귀 기준 |
| 금호석유화학 | 상대적으로 안정적인 downstream packaging | 정상경로 baseline |
| POSCO | 기존 package/application pipeline 교차검증 | downstream baseline |

## Tier 2 — 다음 capability 확장 기업

### LG에너지솔루션
**목적:** 분사(spin-off) 검증.

핵심 질문:
- LG화학 과거자료 중 무엇이 LG에너지솔루션의 과거로 귀속되는가?
- 단순 사명변경과 분사를 시스템이 구분하는가?
- 분사 이전 모회사 전체 자료를 잘못 상속하지 않는가?

합격 기준:
- predecessor를 historical alias로 무조건 검색하지 않는다.
- 사업/사업장 continuity 근거가 있는 범위만 연결한다.
- 불명확한 과거기간은 REVIEW_REQUIRED다.

### 삼성전자 DS
**목적:** 초대형 다사업장 identity/scope 검증.

핵심 질문:
- 기흥, 화성, 평택 등 주요 사업장을 법인명 공통 row와 혼동하지 않는가?
- 동일 주소/유사 이름/본사 정보가 여러 사업장으로 퍼지지 않는가?
- SITE_SET 요청 시 다른 사업장 자료가 user-facing package로 섞이지 않는가?

### 한화에어로스페이스
**목적:** 복잡한 인수합병, 과거 법인명, 방산 계열/사업부 변동, 유사 관계사 검증.

핵심 질문:
- 한화디펜스, 한화지상방산 등 과거 법인/사업 구조를 단순 alias로 합치지 않는가?
- site ownership 기간을 구분하는가?
- 유사 한화 계열사를 원천 raw와 requested scope에서 구분하는가?

### SK하이닉스
**목적:** 복수 대형 생산사업장 + 환경 source coverage 검증.

핵심 질문:
- 이천/청주 등 사업장별 source identity가 안정적으로 유지되는가?
- company-wide 검색 후 SITE_SET narrowing이 정확한가?
- CleanSYS/SOOSIRO/PRTR/화학통계의 서로 다른 site naming을 결합할 수 있는가?

## Tier 3 — 추가 스트레스 유형

향후 필요 시 아래 유형에서 대표 기업을 추가한다.

- 합병으로 법인이 소멸/흡수된 기업
- 사업장 자체가 타 법인으로 양도된 기업
- 공식 홈페이지가 완전히 교체된 기업
- 비상장사로 KIND company code가 없는 사명변경 기업
- 국내/해외 사이트가 같은 이름을 사용하는 기업
- 공공DB에서 법인명보다 브랜드명으로 더 많이 노출되는 기업
- 동일 주소에 여러 환경 인허가 단위가 공존하는 기업

## 실행 규칙

새 기업 검증 시 결과를 네 종류 중 하나로 분류한다.

1. `KNOWN_CAPABILITY_PASS` — 기존 capability로 수정 없이 통과
2. `KNOWN_CAPABILITY_BUG` — 이미 지원한다고 선언한 유형의 회귀
3. `NEW_CAPABILITY_GAP` — 기존 matrix에 없는 구조
4. `LEGITIMATE_REVIEW_REQUIRED` — 공개 근거만으로 자동 확정하는 것이 안전하지 않은 경우

`KNOWN_CAPABILITY_BUG` 또는 `NEW_CAPABILITY_GAP`이 발생하면:

- 실제 실패 artifact를 확인한다.
- 기업별 예외 대신 최소한의 generic rule을 설계한다.
- synthetic regression case를 추가한다.
- 기존 Tier 1 회귀기업을 깨지 않는지 확인한다.
- 실제 E2E를 다시 통과한 뒤 Capability Matrix 상태를 갱신한다.

## 측정할 운영 지표

각 신규기업 batch마다 기록:

| 지표 | 목표 방향 |
|---|---|
| 회사명 한 줄만으로 PASS 비율 | 증가 |
| legitimate REVIEW_REQUIRED 비율 | 안정/감소 |
| 기존 capability regression 수 | 0에 수렴 |
| 신규 capability gap 수 | 감소 |
| 새 기업당 generic production code 변경 수 | 감소 |
| company-specific production exception 수 | 항상 0 |

다음 권장 순서: **한화오션 최종 고정 → LG에너지솔루션 → 삼성전자 DS → 한화에어로스페이스 → SK하이닉스**.
