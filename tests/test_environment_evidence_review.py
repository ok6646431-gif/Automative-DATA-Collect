import csv
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import environment_evidence_review as e


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture(root, company="S-OIL"):
    root = Path(root)
    discovery = []
    for year in (2023, 2024):
        discovery.append({
            "year": year, "compId": "000161472",
            "compNm": company + " 온산공장(온산터미널 포함)",
        })
        htmldir = root / "ENVINFO" / "raw_detail"
        htmldir.mkdir(parents=True, exist_ok=True)
        amount = "55.5" if year == 2023 else "56.63"
        nox = "4,005" if year == 2023 else "3,135.532"
        legal = (
            "<tr><th>환경법규 위반 내용</th><td>SOx 기준 초과로 개선명령</td></tr>"
            "<tr><th>처분기관</th><td>낙동강유역환경청</td></tr>"
            "<tr><th>처분일자</th><td>2023.01.10</td></tr>"
            "<tr><th>처분내용</th><td>개선 명령</td></tr>"
            "<tr><th>조치내용</th><td>운전 절차서 제정</td></tr>"
            "<tr><th>근거법률</th><td>통합관리에 관한 법률 제14조</td></tr>"
            "<tr><th>환경법규 위반 내용</th><td>화학물질 신고 미이행 경고 처분</td></tr>"
            "<tr><th>처분일자</th><td>2023.06.02</td></tr>"
            if year == 2023 else
            "<tr><th>환경법규 위반 내용</th><td>수질 TMS SS 기준초과 개선명령</td></tr>"
            "<tr><th>처분기관</th><td>낙동강유역환경청</td></tr>"
            "<tr><th>처분일자</th><td>2024.09.24</td></tr>"
            "<tr><th>조치내용</th><td>활성탄 여과기 활성탄 교체</td></tr>"
        )
        html = (
            '<html><table><caption>화학물질 배출실적</caption>'
            f'<tr><th>화학물질 배출량</th><td>{amount} ton 전년대비 변동</td></tr>'
            '</table><table><caption>대기오염물질 배출 실적</caption>'
            f'<tr><th>질소산화물(Nox)</th><td>{nox} ton 전년대비 변동</td></tr>'
            '</table><table><caption>환경관련 법규 위반 현황</caption>'
            + legal + '</table></html>'
        )
        (htmldir / f"{year}_000161472_{company}.html").write_text(html, encoding="utf-8")
    _write_csv(root / "ENVINFO" / "discovery.csv", discovery)
    prtr = []
    prtr_detailed = []
    for year, amount in ((2023, "50,722"), (2024, "56,630")):
        prtr.append({
            "search_year": year, "entrps_id": "1021",
            "company_name_raw": company + "(주) 온산공장",
            "address_raw": "울산광역시 울주군 온산읍 온산로 68",
            "release_total_raw": amount,
            "match_status": "UNRESOLVED",
        })
        prtr_detailed.append({
            "search_year": year, "entrps_id": "1021",
            "table_index": 1, "cells": [
                f"{year}년 화학물질 배출량·이동량 정보(kg/년)"
            ],
        })
    _write_csv(root / "PRTR" / "discovery.csv", prtr)
    d = root / "PRTR/detail_table_rows.jsonl"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text("\n".join(map(json.dumps, prtr_detailed)) + "\n", encoding="utf-8")
    chem = [{
        "bplcId": "AAW384N", "reportYear": str(year),
        "bplcNm": company+"(주) 온산공장",
        "locplcAdres": "울산광역시 울주군 온산읍 온산로 68",
    } for year in (2020, 2022, 2024)]
    _write_csv(root / "CHEM_STATS/discovery.csv", chem)
    cleandir = root / "CLEANSYS_AIR"
    cleandir.mkdir(parents=True, exist_ok=True)
    (cleandir / "annual_rows.jsonl").write_text(json.dumps({
        "examin_year": "2024", "fact_code": "130140",
        "fact_manage_nm": company+"㈜ 온산공장", "nox_dscamt": 2345048
    }, ensure_ascii=False)+"\n",encoding="utf-8")
    (cleandir / "candidates.json").write_text(json.dumps([{
        "fact_code": "130140", "company_name_raw": company+"㈜ 온산공장"
    }], ensure_ascii=False),encoding="utf-8")
    (cleandir / "status.json").write_text(json.dumps({
        "status": "DATA_FOUND", "registry_identity_matches": 0,
        "tls_verification": False
    }),encoding="utf-8")
    water = root / "SOOSIRO_WATER"
    water.mkdir(parents=True, exist_ok=True)
    (water / "fact_candidates.json").write_text(json.dumps([{
        "FACT_CODE": "31F0041", "FACT_NAME": company+" 온산공장",
        "FACT_ADDR": "울산광역시 울주군 온산읍 온산로 68"
    }],ensure_ascii=False),encoding="utf-8")
    return root


class PublicEnvironmentalEvidenceTests(unittest.TestCase):
    def test_enforcement_rows_are_source_caption_bound_and_keep_exact_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            result = e.review(root)
            rows = result["violation_rows"]
            self.assertEqual(3, len(rows))
            self.assertEqual(["2023", "2023", "2024"], [r["공개연도"] for r in rows])
            self.assertEqual("2024.09.24", rows[2]["처분일자"])
            self.assertIn("활성탄 여과기", rows[2]["조치내용"])
            self.assertEqual("000161472", rows[2]["ENVINFO사업장ID"])
            self.assertTrue(rows[2]["원문HTML"].startswith("ENVINFO/raw_detail/"))
            self.assertEqual(64, len(rows[2]["원문SHA256"]))
            self.assertEqual([], result["qa_issues"])

    def test_missing_violation_table_is_not_false_announcement_of_zero_offenses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            p = root / "ENVINFO" / "raw_detail" / "2024_000161472_S-OIL.html"
            html = p.read_text(encoding="utf-8")
            first = html.index('<table><caption>환경관련 법규 위반 현황</caption>')
            p.write_text(html[:first] + '</html>', encoding="utf-8")
            result = e.review(root)
            row = next(x for x in result["legal_coverage_rows"] if x["공개연도"]=="2024")
            self.assertEqual("아니오", row["개별표존재"])
            self.assertIn("0건을 입증하지 않음", row["해석주의"])
            self.assertFalse(any("LEGAL_DISCLOSURE_TABLE_MISSING" in x
                                 for x in result["qa_issues"]))

    def test_prtr_units_require_native_header_and_identification_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as temp:
            result = e.review(_fixture(temp))
            rows = {r["연도"]: r for r in result["prtr_comparison_rows"]}
            self.assertEqual("kg/년", rows["2023"]["PRTR원문단위"])
            self.assertEqual(50.722, rows["2023"]["PRTR_환산톤"])
            self.assertAlmostEqual(4.778, rows["2023"]["차이_톤"])
            self.assertEqual("MATERIAL_DIFFERENCE_REVIEW", rows["2023"]["비교판정"])
            self.assertIn("터미널 포함", rows["2023"]["ENVINFO원문사업장표기범위"])
            self.assertNotIn("터미널 포함", rows["2023"]["PRTR원문사업장표기범위"])
            self.assertIn("실제 조사범위 불일치 여부 미확인",
                          rows["2023"]["사업장공개범위차이_참고"])
            self.assertEqual(0, rows["2024"]["차이_톤"])
            self.assertEqual("UNRESOLVED", rows["2023"]["PRTR식별상태"])
            self.assertIn("PRTR_SITE_IDENTITY_UNRESOLVED", result["flags"])
            self.assertIn("PRTR_ENVINFO_MATERIAL_DIFFERENCE_REVIEW", result["flags"])
            self.assertNotIn("자료원 오류 확정", str(result))

    def test_no_air_numeric_comparison_without_captured_unit_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result = e.review(_fixture(temp))
            row = result["air_comparison_rows"][0]
            self.assertEqual(2345048, row["CleanSYS_NOx원문수치"])
            self.assertEqual("3,135.532", row["ENVINFO_NOx원문수치"])
            self.assertEqual("NOT_VERIFIED_IN_CAPTURE", row["CleanSYS_단위검증"])
            self.assertEqual("NOT_VERIFIED_AS_EQUIVALENT", row["집계범위"])
            self.assertEqual(0, row["공개시설명_직접매칭건수"])
            self.assertNotIn("차이_톤", row)
            self.assertIn("CLEANSYS_SOURCE_UNIT_AND_SCOPE_NOT_VERIFIED", result["flags"])

    def test_clean_sys_kg_per_year_from_exact_raw_api_field_title(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            raw = root / "CLEANSYS_AIR/raw_annual/130140_S_OIL_온산공장.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(json.dumps({
                "fieldNm": ["examin_year", "fact_code", "nox_dscamt"],
                "fieldTitle": ["년도", "시설코드", "대기오염물질 연간 배출량(kg/년) - 질소산화물"],
                "ResultList": [{
                    "examin_year": "2024", "fact_code": "130140",
                    "nox_dscamt": 2345048,
                }],
            },ensure_ascii=False),encoding="utf-8")
            result = e.review(root)
            row = result["air_comparison_rows"][0]
            self.assertEqual("kg/년", row["CleanSYS원문단위"])
            self.assertEqual("SOURCE_API_FIELD_TITLE_AND_ROW_VERIFIED", row["CleanSYS_단위검증"])
            self.assertAlmostEqual(2345.048, row["CleanSYS_NOx환산톤"])
            self.assertIn("질소산화물", row["CleanSYS_원문필드제목"])
            self.assertEqual(64, len(row["CleanSYS_원문SHA256"]))
            self.assertEqual("NOT_VERIFIED_AS_EQUIVALENT", row["집계범위"])
            self.assertEqual("UNIT_VERIFIED_SCOPE_UNCONFIRMED_NO_DIRECT_DIFFERENCE", row["비교판정"])
            self.assertNotIn("차이_톤", row)
            self.assertIn("CLEANSYS_SOURCE_UNIT_VERIFIED_SCOPE_NOT_VERIFIED", result["flags"])
            self.assertNotIn("CLEANSYS_SOURCE_UNIT_AND_SCOPE_NOT_VERIFIED", result["flags"])

    def test_clean_sys_rejects_another_facility_or_year_as_unit_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            raw = root / "CLEANSYS_AIR/raw_annual/130140_S_OIL_온산공장.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(json.dumps({
                "fieldNm": ["examin_year","fact_code","nox_dscamt"],
                "fieldTitle": ["년도","시설코드","대기오염물질 연간 배출량(kg/년) - 질소산화물"],
                "ResultList": [{
                    "examin_year": "2023", "fact_code": "130140",
                    "nox_dscamt": 2345048,
                }],
            },ensure_ascii=False),encoding="utf-8")
            row = e.review(root)["air_comparison_rows"][0]
            self.assertEqual("NOT_VERIFIED_IN_CAPTURE",row["CleanSYS_단위검증"])
            self.assertEqual("",row["CleanSYS_NOx환산톤"])

    def test_prtr_address_candidate_remains_unconfirmed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            p = root / "PRTR/discovery.csv"
            records = e._csv(p)
            for row in records:
                row["match_status"] = "ADDRESS_CANDIDATE"
                row["proposed_site_ids"] = "온산공장"
            _write_csv(p, records)
            result = e.review(root)
            self.assertIn("PRTR_SITE_IDENTITY_CANDIDATE_NOT_CANONICAL", result["flags"])
            self.assertNotIn("PRTR_SITE_IDENTITY_UNRESOLVED", result["flags"])
            self.assertTrue(all("식별 미확정" in r["처리원칙"]
                                for r in result["prtr_comparison_rows"]))
            prtr = [r for r in result["identity_rows"] if r["자료원"]=="PRTR"]
            self.assertTrue(prtr)
            self.assertIn("미확정",prtr[0]["주의"])

    def test_no_prtr_ton_conversion_without_source_native_header(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            (root/"PRTR/detail_table_rows.jsonl").write_text("",encoding="utf-8")
            rows = e.review(root)["prtr_comparison_rows"]
            self.assertEqual("PRTR_UNIT_OR_NUMBER_NOT_SOURCE_VERIFIED", rows[0]["비교판정"])
            self.assertEqual("", rows[0]["차이_톤"])
            self.assertEqual("미확인", rows[0]["PRTR원문단위"])

    def test_missing_or_ambiguous_site_does_not_silently_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _fixture(temp)
            path = root/"PRTR/discovery.csv"
            records = e._csv(path)
            for r in records:
                r["company_name_raw"] = "다른법인 본사"
            _write_csv(path, records)
            rows = e.review(root)["prtr_comparison_rows"]
            self.assertEqual("SITE_PAIRING_AMBIGUOUS_OR_MISSING", rows[0]["비교판정"])
            self.assertEqual("", rows[0]["차이_톤"])

    def test_generic_company_name_and_source_ids_not_company_hardcoded(self):
        with tempfile.TemporaryDirectory() as temp:
            result = e.review(_fixture(temp, "가나다정유"))
            self.assertEqual(3,len(result["violation_rows"]))
            self.assertEqual(2,len(result["prtr_comparison_rows"]))
            self.assertEqual("1021", next(r["원본식별자"] for r in result["identity_rows"]
                                          if r["자료원"] == "PRTR"))


if __name__ == "__main__":
    unittest.main()
