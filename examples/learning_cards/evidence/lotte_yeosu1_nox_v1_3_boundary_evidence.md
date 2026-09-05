# Evidence Supplement — 롯데케미칼 여수1공장 NOx 자료경계 검증

- `evidence_pack_id`: `lotte-yeosu1-nox-v1.3-boundary`
- `verified_at`: `2026-08-30`
- `purpose`: CleanSYS와 ENV-INFO의 여수1공장 NOx 연간값이 왜 직접 일치하지 않는지, 확인된 자료경계와 아직 미확인인 부분을 분리한다.
- `source_run`: GitHub Actions Run `32207203874`
- `source_artifact`: `enterprise-env-final` / artifact `9349718913`

---

## B01 — 여수1공장은 TMS와 기타 배출구 측정을 함께 운영했다고 공개했다

**상태:** `VERIFIED / COMPANY_DISCLOSURE`

### 2020 ENV-INFO 원문

- 사업장: `롯데케미칼(주)여수1공장`
- COMP_ID: `00000000000000151200`
- 원문 section: `대기오염물질 모니터링 시스템 현황`
- source locator:
  `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2020&COMP_ID=00000000000000151200&OPEN_YN=Y`
- frozen raw:
  `output/ENVINFO/raw_detail/2020_00000000000000151200_롯데케미칼_주_여수1공장.html`
- SHA-256:
  `4a3eaef3828908526a870c8876c5d5e69baf581094cf733bb8ff0ba2e21fe6b4`

원문 anchor:

```text
모니터링 주기 실시간 ~ 1회/년
모니터링 방법
1. T.M.S : 5초 간격으로 sampling 및 분석결과 전송
2. 기타 배출구 : 오염물질별 측정주기 준수(1회/2주 ~ 1회/년)
```

같은 화면에서 NOx 배출실적은 `296 ton`으로 공개된다.

### 의미

`여수1공장`이라는 하나의 사업장 안에서도 대기배출 모니터링이 모두 TMS 한 방식으로만 이루어진 것이 아님을 회사 공개자료 자체가 보여준다.

따라서:

> 같은 사업장명 = CleanSYS와 ENV-INFO가 반드시 같은 배출구 집합을 집계한다

라고 가정하면 안 된다.

---

## B02 — 2021년에도 TMS와 기타 배출구가 명시적으로 구분됐다

**상태:** `VERIFIED / COMPANY_DISCLOSURE`

- source locator:
  `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2021&COMP_ID=00000000000000151200&OPEN_YN=Y`
- frozen raw:
  `output/ENVINFO/raw_detail/2021_00000000000000151200_롯데케미칼_주_여수1공장.html`
- SHA-256:
  `3c6d9efa014ca2fd1487ee4f1334d455c8bd0d2a1c78fdf9e22b5fd7f88ccd66`

원문 anchor:

```text
모니터링 주기 실시간~1회/년
모니터링 방법
1. T.M.S - 5초 간격으로 sampling 및 분석결과 전송
2. 기타 배출구 : 오염물질별 측정주기 설립 및 준수(1회/2주~1회/년)
```

추가로 같은 연도 자료에는 Flare Stack OGI Camera 상시 모니터링도 별도로 기재되어 있다.

같은 화면의 NOx 배출실적은 `1,980.956 ton`이다.

### 의미

2021년의 CleanSYS `249,474 kg/년`과 ENV-INFO `1,980.956 ton`의 차이를 단순 전사·단위 오류로 설명하기 전에, **측정·산정 대상 배출구와 자료생성방식이 다를 수 있음을 반드시 검토해야 한다.**

다만 이 원문만으로 ENV-INFO `1,980.956 ton`이 정확히 `TMS 배출량 + 모든 기타 배출구 배출량`의 단순합이라고 증명되는 것은 아니다.

**정확한 수치 reconciliation:** `NEEDS_EVIDENCE`

---

## B03 — 후속 연도에도 TMS와 자가측정이 병행됐다

**상태:** `VERIFIED / COMPANY_DISCLOSURE`

### 2023

- locator:
  `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2023&COMP_ID=00000000000000151200&OPEN_YN=Y`
- SHA-256:
  `caec0d5fb596cec5ebf8b23bc5bfc2f61dedf04460306647c99da4515abfdc5b`

원문에는:

- `TMS 설비로 먼지/SOx/NOx 중 대상 항목 실시간 모니터링`
- `대기자가측정을 통한 배출구별 오염물질 허용기준 준수 여부 파악`

이 함께 기재되어 있다.

### 2024

- locator:
  `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2024&COMP_ID=00000000000000151200&OPEN_YN=Y`
- SHA-256:
  `2b7d538a76fff4a9aebea2e0e7f628bf2c546f2751ae4db5189049b958e2415d`

원문에는:

- `TMS 부착설비` 실시간 모니터링
- `대기자가측정을 통해 배출구 별 대기오염물질의 배출허용기준 준수 여부 파악`

이 함께 기재되어 있다.

### 의미

여수1공장의 대기관리는 지속적으로 **TMS 부착설비 + TMS가 아닌 배출구의 별도 측정·관리**가 함께 존재하는 구조로 공개되어 왔다.

---

## B04 — ENV-INFO 공식 등록 가이드라인은 1~3종 사업장에 SEMS 자료를 우선하도록 안내한다

**상태:** `VERIFIED / OFFICIAL_GUIDANCE / checked_as_of=2026-08-30`

공식 자료:
`2024년 환경정보공개제도 등록 가이드라인`, 항목 `14. 대기오염물질 배출량`, 인쇄면 p.85~88.

공식 PDF:
`https://www.env-info.kr/v2/publish/testfiles/2024년%20환경정보공개제도%20등록%20가이드라인.pdf`

핵심 내용:

- 1~3종 사업장은 대기오염물질 배출량 항목을 의무 작성.
- 대기환경배출원관리시스템(SEMS)에 제출한 대기오염물질 배출량을 기준으로 작성.
- SEMS 제출과 TMS 운영이 동시에 이루어지는 경우에도 SEMS 자료를 기준으로 작성.
- 동일 배출구에서 자가측정과 TMS/IoT 측정이 동시에 이루어지는 경우에는 측정기기를 통해 산정된 값을 사용.
- SEMS/TMS 등의 단위는 kg, 환경정보공개시스템은 ton이므로 단위에 유의.
- 증빙자료 우선순위에도 SEMS 대기오염원 배출원 조사서를 우선하고 TMS 운영일지/자가측정기록부를 보조근거로 제시.

### 시간경계 주의

이 자료는 **2024년 공식 등록 가이드라인**이다.

따라서 이 문서만으로 `2021년에도 문구가 완전히 동일했다`고 소급 단정하지 않는다.

- `2024 guidance rule`: `VERIFIED`
- `exact 2021 ENV-INFO registration rule text`: `NEEDS_EVIDENCE`

그러나 B02의 2021 롯데 원문 자체가 TMS와 기타 배출구를 병행 관리했다고 명시하므로, **2021년에도 CleanSYS=TMS계열 자료와 ENV-INFO 사업장 공개값을 자동 동일경계로 볼 수 없다는 결론**은 유지된다.

---

## B05 — SEMS는 TMS보다 넓은 사업장·시설 운영정보를 수집하는 배출원 관리체계다

**상태:** `VERIFIED / OFFICIAL_SYSTEM / checked_as_of=2026-08-30`

공식 국가미세먼지정보센터 자료:

- SEMS 소개:
  `https://air.go.kr/contents/view.do?contentsId=5&menuId=35`
- 대기배출원 조사방법:
  `https://air.go.kr/contents/view.do?contentsId=7&menuId=37`
- 현행 SEMS:
  `https://sems.air.go.kr/`

현재 공식 설명상 1~3종 사업장은 SEMS를 통해 사업장현황, 배출구·배출시설·방지시설 정보, 운영기록, 자가측정정보, 원료·연료·제품 사용량 등을 제출·관리한다. 조사체계에는 한국환경공단 TMS 확정자료도 활용된다.

### 의미

SEMS와 CleanSYS를 다음처럼 구분해 이해한다.

```text
CleanSYS / TMS
- TMS가 설치된 굴뚝의 연속측정·전송 자료

SEMS
- 1~3종 사업장의 배출원 관리 DB
- 사업장/시설/배출구 정보
- 가동정보
- 자가측정
- 연료·원료·생산 활동도
- TMS 자료 등 여러 자료를 함께 관리
```

따라서 `TMS가 실시간이므로 ENV-INFO보다 더 정확하다`는 식의 단일 서열은 적절하지 않다.

더 정확한 구분은:

- **TMS:** 부착 굴뚝에 대한 높은 시간해상도·직접 측정이라는 강점
- **SEMS/ENV-INFO:** 사업장 배출원 관리·공개에서 더 넓은 시설/자료 경계를 가질 수 있음

이다.

---

# 현재 검증 결론

## 확인된 것

1. CleanSYS와 ENV-INFO의 단위 차이는 이미 확인·환산 가능하다.
2. 여수1공장은 실제로 TMS와 기타 배출구 측정을 병행했다고 2020·2021년에 공개했다.
3. 2023·2024에도 TMS와 자가측정이 병행되었다.
4. 2024 공식 ENV-INFO 가이드라인은 1~3종 사업장 배출량 작성 시 SEMS 제출자료를 기준으로 하도록 안내한다.
5. 현재 SEMS 공식 설명은 SEMS가 TMS 자료뿐 아니라 시설·운영·자가측정·활동도 자료를 함께 관리하는 체계임을 보여준다.

## 아직 확인되지 않은 것

1. `2021 ENV-INFO 1,980.956 ton`을 구성한 배출구별 SEMS 세부값.
2. `2021 CleanSYS 249.474 ton`과 ENV-INFO 값의 배출구별 수치 reconciliation.
3. 2021년 당시 ENV-INFO 등록 가이드라인의 정확한 SEMS/TMS 우선 문구.
4. 2020~2025 TMS 신규 부착·제외 배출구의 연도별 매핑.

따라서 최종 표현은 다음 수준으로 제한한다.

> **[확인됨]** 여수1공장은 TMS 부착설비와 기타 배출구를 서로 다른 방식으로 측정·관리한다고 공개했고, 공식 ENV-INFO 가이드라인은 1~3종 사업장의 대기배출량을 SEMS 자료에 기반해 작성하도록 안내한다. 따라서 CleanSYS와 ENV-INFO는 같은 사업장명을 사용하더라도 자동으로 동일한 데이터 제품·측정경계를 뜻하지 않는다.
>
> **[추가확인]** 2021년 두 NOx 값의 정확한 수치 차이를 설명하려면 당시 SEMS 배출구별 자료와 TMS 배출구 매핑이 추가로 필요하다.
