# Evidence Pack — 롯데케미칼 여수1공장 NOx Learning Card v1.1

- `evidence_pack_id`: `lotte-yeosu1-nox-v1.1`
- `verified_at`: `2026-08-30`
- `source_run`: GitHub Actions Run `32207203874` (`acceptance/lottechem-discovery`)
- `source_commit`: `eced051adffe62c73e3015d0cd7d8184d9a9e906`
- `source_artifact`: `enterprise-env-final` / artifact `9349718913`
- `artifact_digest`: `sha256:8a7c6bac59e20b1632ae2478011f8c533043c552cccc463de4195670181743ec`

이 파일은 학습카드의 E02/E03/E04가 실제 수집 원문으로 되돌아갈 수 있도록 **공식 endpoint + 요청키 + 원자료 내부 위치 + SHA-256 + 원문 anchor**를 고정한다.

---

## E02 — CleanSYS NOx annual rows

**상태:** `VERIFIED`

### 공식 locator

- 사용자 화면: `https://cleansys.or.kr/statAnnual.do`
- 원응답 API: `https://cleansys.or.kr/apiService/selectAnnualResult.do`
- 요청 방식: `POST`
- 요청 form:

```text
s_year=2015
e_year=2025
selectArea=
selectComp=
selectCompDrop=110019
selectOrder=
type=json
```

`selectCompDrop=110019`는 수집 당시 CleanSYS 사업장 목록의 `롯데케미칼㈜ 여수1공장`에 대응한다.

### 동결 원자료

- artifact 내부 경로: `output/CLEANSYS_AIR/raw_annual/110019_롯데케미칼_여수1공장.json`
- SHA-256: `537e70adb08296f319a433b4ce5dfc6db51d7c892de49bbf03faf3c99060fe53`
- 원응답 필드명: `대기오염물질 연간 배출량(kg/년) - 질소산화물`
- JSON field: `nox_dscamt`

| year | fact_code | source site name | `nox_dscamt` | source unit |
|---:|---|---|---:|---|
| 2020 | 110019 | 롯데케미칼㈜ 여수1공장 | 266,169 | kg/년 |
| 2021 | 110019 | 롯데케미칼㈜ 여수1공장 | 249,474 | kg/년 |
| 2022 | 110019 | 롯데케미칼㈜ 여수1공장 | 201,404 | kg/년 |
| 2023 | 110019 | 롯데케미칼㈜ 여수1공장 | 31,297 | kg/년 |
| 2024 | 110019 | 롯데케미칼㈜ 여수1공장 | 48,574 | kg/년 |
| 2025 | 110019 | 롯데케미칼㈜ 여수1공장 | 48,105 | kg/년 |

**해석 경계:** 이 값은 CleanSYS 원응답의 연간 NOx 필드라는 사실까지 확인되었다. ENV-INFO 사업장 총량과 같은 집계경계라는 뜻은 아니다.

---

## E03 — ENV-INFO NOx total

**상태:** `VERIFIED`

- `COMP_ID`: `00000000000000151200`
- source site name: `롯데케미칼(주)여수1공장`
- 원문 section: `대기오염물질 배출 실적`
- 원문 row label: `질소산화물(Nox)`
- 화면 표시 단위: `ton`

| 공개연도 | 원문 표시값 | 공식 detail locator | 동결 HTML SHA-256 |
|---:|---:|---|---|
| 2020 | 296 ton | `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2020&COMP_ID=00000000000000151200&OPEN_YN=Y` | `4a3eaef3828908526a870c8876c5d5e69baf581094cf733bb8ff0ba2e21fe6b4` |
| 2021 | 1,980.956 ton | `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2021&COMP_ID=00000000000000151200&OPEN_YN=Y` | `3c6d9efa014ca2fd1487ee4f1334d455c8bd0d2a1c78fdf9e22b5fd7f88ccd66` |
| 2022 | 1,630.856 ton | `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2022&COMP_ID=00000000000000151200&OPEN_YN=Y` | `eb072d89e297e3b1760708cbe6a50b6e519e684e02a7898e6cea5ef3f7b52cb5` |
| 2023 | 1,040.753 ton | `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2023&COMP_ID=00000000000000151200&OPEN_YN=Y` | `caec0d5fb596cec5ebf8b23bc5bfc2f61dedf04460306647c99da4515abfdc5b` |
| 2024 | 870.912 ton | `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2024&COMP_ID=00000000000000151200&OPEN_YN=Y` | `2b7d538a76fff4a9aebea2e0e7f628bf2c546f2751ae4db5189049b958e2415d` |

artifact 내부 원문은 각각 `output/ENVINFO/raw_detail/{YEAR}_00000000000000151200_롯데케미칼_주_여수1공장.html`에 저장되어 있었다.

### E02와 E03을 바로 합치면 안 되는 이유가 더 명확해짐

단위는 이제 확인되었다.

- CleanSYS: `kg/년`
- ENV-INFO: 화면 표시 `ton`

그러나 단위만 환산해도 값이 일치하지 않는다. 예를 들어 2021년 CleanSYS 값은 `249,474 kg/년 = 249.474 ton/년`인 반면 ENV-INFO 화면은 `1,980.956 ton`이다. 따라서 남은 핵심 확인사항은 **포함 배출구, TMS 측정범위, 비부착 배출원 처리, 사업장 총량 산정방식 등 집계경계**다.

---

## E04 — ENV-INFO company actions

**상태:** `VERIFIED`

모든 항목의 원문 section은 `대기·수질, 폐기물 및 화학물질 관련 투자 및 기술 도입 현황`이다.

### A. 2020 H-COG, HRSG

- 공식 locator: `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2020&COMP_ID=00000000000000151200&OPEN_YN=Y`
- 원문 anchor: `H-COG, HRSG`
- 총사업기간: `2019.05.01 - 2020.06.30`
- 총투자비: `360 백만원`
- 사업내용: `SCR 촉매 노후 재생 및 교체`
- 회사 공개 효과: `SCR 촉매교체에 따른 NOx 저감. (242,966 → 201,903 Kg)`
- 동결 HTML SHA-256: `4a3eaef3828908526a870c8876c5d5e69baf581094cf733bb8ff0ba2e21fe6b4`

### B. 2020 여수공장(H-COG, H-PC) 보일러

- 공식 locator: 위 2020 detail page와 동일
- 원문 anchor: `여수공장(H-COG, H-PC) 보일러`
- 총사업기간: `2019.07.01 - 2020.07.31`
- 총투자비: `1,200 백만원`
- 사업내용: `NOx 저감설비(SCR) 신설`
- 회사 공개 효과: `SCR 신설에 따른 NOx 저감. (421 → 296 Ton)`

### C. 2021 H-NC 분해로 BA-111~114

- 공식 locator: `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2021&COMP_ID=00000000000000151200&OPEN_YN=Y`
- 원문 anchor: `H-NC, 분해로(BA-111~114) NOx 저감 Burner 적용`
- 총사업기간: `2021.09.01 - 2021.12.12`
- 총투자비: `6,631 백만원`
- 사업내용: `H-NC, 분해로(BA-111~114) NOx 저감 Burner 적용`
- 회사 공개 효과: `Ultra Low Burner 적용으로 NOx 배출농도 감소효과. 73.3ppm → 약 45ppm으로 감소(배출허용기준 - 75ppm)`
- 동결 HTML SHA-256: `3c6d9efa014ca2fd1487ee4f1334d455c8bd0d2a1c78fdf9e22b5fd7f88ccd66`

### D. 2021 H-COG Boiler

- 공식 locator: 위 2021 detail page와 동일
- 원문 anchor: `H-COG, Boiler 저 NOx Burner`
- 총사업기간: `2021.11.11 - 2022.12.31`
- 총투자비: `1,100 백만원`
- 사업내용: `H-COG, Boiler 저 NOx Burner 교체`
- 회사 공개 효과: `저NOx 버너 적용으로 NOx 배출량 감소 효과.`
- 회사 공개 설명: `대기관리권역법에 따른 사업장 NOx 할당량 준수 가능 및 NOx 잔여량 판매 기대.`

### E. 2021~2023 TMS 확대

- 공식 locator: 위 2021 detail page와 동일
- 원문 anchor: `TMS(굴뚝 자동측정기기) 설비 확대설치`
- 총사업기간: `2021.03.01 - 2023.12.31`
- 총투자비: `9,900 백만원`
- 사업내용: `TMS(굴뚝 자동측정기기) 설비 확대설치 - NC 분해로(6기) 등`
- 회사 공개 효과: `실시간 설비 대기배출오염물질 배출허용기준 준수 여부 확인 가능. 설비 운전 이상 발생시 즉각적인 대처 가능.`
- 2022·2023 ENV-INFO에도 `TMS 설비로 먼지/SOx/NOx 중 대상 항목 실시간 모니터링 중`이라고 공개됨.

### F. 2022~2025 BA-101~110 순차 적용 계획

- 공식 locator: `https://www.env-info.kr/user/register/viewUserSearch2.do?YEAR=2022&COMP_ID=00000000000000151200&OPEN_YN=Y`
- 원문 anchor: `H-NC, 분해로(BA-101~110) NOx 저감 Burner 적용`
- 총사업기간: `2022.07.01 - 2025.05.31`
- 총투자비: `19,400 백만원`
- 사업내용: `H-NC, 분해로(BA-101~110) NOx 저감 Burner 적용 (1~3차 물량으로 순차 진행 예정)`
- 회사 공개 목표:
  - BA-101: 기존 `NOx <100 ppm` → 변경 `NOx <50 ppm`
  - BA-102~108: 기존 `NOx <250 ppm` → 변경 `NOx <50 ppm`
  - BA-109~110: 기존 `NOx <200 ppm` → 변경 `NOx <50 ppm`
- 동결 HTML SHA-256: `eb072d89e297e3b1760708cbe6a50b6e519e684e02a7898e6cea5ef3f7b52cb5`

2023 detail page에서도 같은 BA-101~110 저NOx Burner 적용 항목이 다시 확인되며, 해당 연도 공개 총사업기간은 `2023.01.01 - 2023.12.31`, 총투자비는 `5,820 백만원`으로 표시된다.

---

## Interpretation boundary

이 Evidence Pack으로 확인되는 것은 다음까지다.

1. E02의 CleanSYS 장기 NOx 값과 단위가 공식 원응답에 존재한다.
2. E03의 ENV-INFO NOx total 값이 여수1공장 각 연도 detail 화면에 존재한다.
3. E04의 SCR·저NOx Burner·TMS 조치가 같은 사업장 ENV-INFO에 실제 공개되어 있다.

**확인되지 않은 것:**

- CleanSYS와 ENV-INFO의 집계경계가 동일하다는 주장
- 특정 저NOx Burner/SCR 조치와 2023년 CleanSYS 급감 사이의 직접 인과관계
- 여수1공장의 개별 통합허가 조건 및 해당 조치별 변경허가/변경신고 이력
- 각 분해로의 실제 운전개시일, 가동시간, 생산부하

따라서 위 항목들은 계속 `NEEDS_EVIDENCE` 또는 `DO_NOT_INFER`로 유지한다.
