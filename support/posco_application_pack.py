from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

ROOT = Path('posco-pack')
DOC = ROOT / '01_공식보고서'
PAGE = ROOT / '02_환경직_핵심공식페이지'
LEGAL = ROOT / '03_법인_사업장'
INDEX = ROOT / '00_자료목록'

ARCHIVE_URL = 'https://sustainability.posco.com/S91/S91F10/kor/cmspage.do?mmcd=2645996979005381'
ENV_URL = 'https://sustainability.posco.com/S91/S91F10/kor/cmspage.do?mmcd=2676068505003781'
CLIMATE_URL = 'https://sustainability.posco.com/S91/S91F10/kor/cmspage.do?mmcd=2648825310001950'
FACTBOOK_PAGE_URL = 'https://sustainability.posco.com/S91/S91F10/kor/cmspage.do?mmcd=2681672717001150'
DIVISION_URL = 'https://posco.com/homepage/docs/kor7/jsp/resources/file/ir/220302_end_of_division.pdf'

KNOWN = [
    (2025, '지속가능경영보고서', 'https://sustainability.posco.com/S91/S91F10/download.do?fid=260000065&pid=123', '2025_POSCO_지속가능경영보고서_KOR.pdf'),
    (2025, 'ESG Factbook', 'https://sustainability.posco.com/S91/S91F10/download.do?fid=260000066&pid=124', '2025_POSCO_ESG_Factbook.pdf'),
    (2024, 'ESG Factbook', 'https://sustainability.posco.com/assets/file/2024_POSCO_ESG_Factbook.pdf', '2024_POSCO_ESG_Factbook.pdf'),
    (2023, 'ESG Factbook', 'https://sustainability.posco.com/assets/file/2023_POSCO_ESG_Factbook.pdf', '2023_POSCO_ESG_Factbook.pdf'),
    (2022, '지속가능경영보고서', 'https://sustainability.posco.com/assets/file/POSCO_Sustainability_Report_2022_eng.pdf', '2022_POSCO_Sustainability_Report_ENG.pdf'),
    (2022, 'ESG Factbook', 'https://sustainability.posco.com/assets/file/2022_POSCO_ESG_Factbook.pdf', '2022_POSCO_ESG_Factbook.pdf'),
    (2021, '기업시민보고서', 'https://sustainability.posco.com/assets/file/POSCO_Sustainability_Report_2021_eng.pdf', '2021_POSCO_Corporate_Citizenship_Report_ENG.pdf'),
    (2021, 'ESG Factbook', 'https://sustainability.posco.com/assets/file/2021_POSCO_ESG_Factbook.pdf', '2021_POSCO_ESG_Factbook.pdf'),
    (2021, 'ESG Policybook', 'https://sustainability.posco.com/assets/file/2021_POSCO_Policybook.pdf', '2021_POSCO_ESG_Policybook.pdf'),
]

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (public official document collector)'})


def mkdirs():
    for p in [DOC, PAGE, LEGAL, INDEX]:
        p.mkdir(parents=True, exist_ok=True)


def download_pdf(url: str, out: Path, timeout=25):
    try:
        r = S.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        if not r.content.startswith(b'%PDF'):
            return False, f'not_pdf:{r.headers.get("content-type", "")}'
        out.write_bytes(r.content)
        return True, f'{len(r.content)} bytes'
    except Exception as e:
        return False, f'{type(e).__name__}:{str(e)[:160]}'


def collect():
    mkdirs()
    rows = []
    for year, cat, url, name in KNOWN:
        ok, note = download_pdf(url, DOC / name)
        rows.append([cat, year, name, url, '다운로드 완료' if ok else '다운로드 실패', note])
    rows.append(['기업시민보고서', 2020, 'POSCO_지속가능경영보고서_공식아카이브.pdf', ARCHIVE_URL,
                 '공식 아카이브 PDF에 존재 확인', '지원서 즉시사용팩: 2020 원문 파일 경로 자동복원은 전체 수집 파이프라인에서 별도 처리'])
    ok, note = download_pdf(DIVISION_URL, LEGAL / '2022_포스코_물적분할_공식자료.pdf')
    rows.append(['법인경계', 2022, '2022_포스코_물적분할_공식자료.pdf', DIVISION_URL, '다운로드 완료' if ok else '다운로드 실패', note])
    (ROOT / '_collection_rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


def style(ws):
    fill = PatternFill('solid', fgColor='D9EAF7')
    for c in ws[1]:
        c.font = Font(bold=True); c.fill = fill; c.alignment = Alignment(horizontal='center', vertical='center')
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
    for i in range(1, ws.max_column + 1):
        vals = [str(c.value or '') for c in ws[get_column_letter(i)]]
        ws.column_dimensions[get_column_letter(i)].width = min(58, max(12, max(map(len, vals), default=10) + 2))
        for c in ws[get_column_letter(i)]: c.alignment = Alignment(vertical='top', wrap_text=True)


def finalize():
    rows = json.loads((ROOT / '_collection_rows.json').read_text(encoding='utf-8'))
    for name, url, note in [
        ('2025_POSCO_환경영향_공식페이지.pdf', ENV_URL, '환경조직, 인허가, 배출방지시설, 화학물질, 폐기물, 환경투자'),
        ('2025_POSCO_기후변화_공식페이지.pdf', CLIMATE_URL, '기후변화 및 탄소중립'),
        ('2025_POSCO_ESG_Factbook_공식페이지.pdf', FACTBOOK_PAGE_URL, '최신 ESG 데이터'),
        ('POSCO_지속가능경영보고서_공식아카이브.pdf', ARCHIVE_URL, '2020~2025 공식 보고서 아카이브'),
    ]:
        rows.append(['공식 ESG 웹페이지', 2025 if name.startswith('2025') else '', name, url,
                     'PDF 저장 완료' if (PAGE/name).exists() else 'PDF 저장 실패', note])

    wb = Workbook(); ws = wb.active; ws.title = '자료목록'
    ws.append(['분류','연도','파일명','공식 출처 URL','상태','비고'])
    for r in rows: ws.append(r)
    style(ws)

    ws2 = wb.create_sheet('환경핵심지표_2022_2024')
    ws2.append(['지표','단위',2022,2023,2024,'출처/주의사항'])
    metrics = [
        ['Scope 1&2 온실가스','tCO2e',70185623,71971900,71065170,'2024 POSCO ESG Factbook'],
        ['에너지 사용량','GJ',333781599,354002733,359242804,'2022 포항·광양, 2023~2024 전사 기준'],
        ['대기오염물질 총배출량','ton',53451,55042,49340,'2022·2023 조정값'],
        ['NOx','ton',27653,27685,23909,'2024 POSCO ESG Factbook'],
        ['SOx','ton',23294,23945,22366,'2024 POSCO ESG Factbook'],
        ['Dust','ton',2504,3413,3065,'2024 POSCO ESG Factbook'],
        ['폐기물 발생량','ton',19116690,19523970,20203736,'2024 POSCO ESG Factbook'],
        ['폐기물 재활용률','%',98.3,98.6,98.8,'2024 POSCO ESG Factbook'],
        ['용수 취수량(포항·광양)','ton',145115608,153645403,156026930,'2024 POSCO ESG Factbook'],
        ['용수 재사용률(포항·광양)','%',23.5,20.8,19.3,'2024 POSCO ESG Factbook'],
        ['BOD','ton',191.114,203.841,193.728,'2024 POSCO ESG Factbook'],
        ['T-N','ton',684.976,668.257,879.314,'2022·2023 확정값 조정'],
        ['T-P','ton',3.827,2.073,5.717,'2024 POSCO ESG Factbook'],
        ['SS','ton',134.747,134.238,160.598,'2022·2023 확정값 조정'],
        ['TOC','ton',None,288.780,343.460,'COD→TOC 전환으로 2022 TOC 활용 불가'],
        ['환경 법규 위반','건',9,8,12,'2023 중복집계 등 조정'],
    ]
    for r in metrics: ws2.append(r)
    style(ws2)

    ws3 = wb.create_sheet('지원서용_환경직포인트')
    ws3.append(['구분','공식자료에서 확인되는 내용','지원서 활용','출처'])
    for r in [
        ['환경조직','대표이사 산하 안전보건환경본부, 환경에너지기획실, 제철소 환경자원그룹','현장 관리와 본사 전략을 연결하는 직무 구조',ENV_URL],
        ['환경자원그룹','환경관리체계 수립·운영, 인허가 주관, 배출방지시설 점검, 화학물질 교육 실적 관리, 폐기물 재활용 처리','직무 이해 근거',ENV_URL],
        ['규제 대응','국내외 탄소규제, 에너지정책, 온실가스 외부평가 대응','법규·정책 대응 역량과 연결',ENV_URL],
        ['환경투자','2020~2025 총 2조 2,946억원: 대기 19,953억, 수질 2,636억, 부산물 127억, 화학물질·토양 등 230억','TMS, SCR/SNCR, 집진, 폐수처리, 유해화학물질 설비와 연결',ENV_URL],
        ['핵심 사업장','포항제철소, 광양제철소','사업장 단위 환경관리 관점','https://sustainability.posco.com/S91/S91F10/kor/cmspage.do?mmcd=2645916083001125'],
    ]: ws3.append(r)
    style(ws3)

    ws4 = wb.create_sheet('법인경계_주의'); ws4.append(['항목','내용'])
    for r in [
        ['현재 지원 대상','철강 사업회사 주식회사 포스코(POSCO)'],
        ['2022 경계','2022-03-01 물적분할로 현재 포스코가 신설되고 기존 법인은 포스코홀딩스로 존속'],
        ['2020~2021','분할 전 철강사업 역사자료. 현재 포스코와 동일 법인이라고 표기하지 않음'],
        ['2022 이후','현재 철강 사업회사 포스코 자료'],
        ['해석 원칙','포항·광양 제철소 철강사업의 운영 연속성과 법인 동일성은 구분'],
    ]: ws4.append(r)
    style(ws4)

    wb.save(INDEX/'포스코_지원용_자료목록_및_환경핵심데이터.xlsx')
    (ROOT/'README_먼저보기.txt').write_text(
        '포스코 안전/보건/환경 지원서 작성용 즉시사용 자료세트\n\n'
        '00_자료목록 XLSX부터 보세요. 02_환경직_핵심공식페이지의 환경영향 PDF가 직무 조사 핵심입니다.\n'
        '2020~2021은 2022 물적분할 이전 철강사업 역사자료이며 현재 포스코와 동일 법인이라고 단정하지 않습니다.\n'
        '이 팩은 지원서 작성용 간이팩으로 ENV-INFO/PRTR/CleanSYS/SOOSIRO 전체 수집 패키지는 아닙니다.\n', encoding='utf-8')
    (ROOT/'_collection_rows.json').unlink(missing_ok=True)
    print('files', len([p for p in ROOT.rglob('*') if p.is_file()]))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--stage', choices=['collect','finalize'], required=True); a = ap.parse_args()
    collect() if a.stage == 'collect' else finalize()
