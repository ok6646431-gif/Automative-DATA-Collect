"""Keep ENV-INFO report attachments distinct from original corporate annual reports.

The ENV-INFO user folder already contains the original attached files. Promoted
copies of these same files must not occupy the corporate annual-report lane or
inflate its minimum-five-files acceptance gate.
"""
from pathlib import Path


def keep_envinfo_out_of_official_annual_lane(original_promoter):
    """Wrap ENV-INFO promotion without changing the source attachments or policies."""
    def promote(package_root, archive_root, scope, company_name):
        created = original_promoter(package_root, archive_root, scope, company_name)
        official_lane = Path(archive_root) / '01_사용자자료' / '04_지속가능경영보고서'
        kept = []
        for path in created:
            promoted = Path(path)
            if promoted.parent == official_lane:
                # The promoter is the source of provenance, not the file name.
                # unique_copy can return the same path for several source rows.
                # Never delete the original attachment in the 03 provenance lane.
                if promoted.exists():
                    promoted.unlink()
                continue
            kept.append(path)
        return kept
    return promote


def provenance_specific_user_guide(original_writer):
    """Keep the human guide accurate before archive indexes and ZIP are finalized.

    The canonicalizer later moves source attachments to 03/첨부자료_원문 and records
    source-site/year to final-path mappings in ENVINFO_첨부자료_참조표.xlsx.  This
    reference marker also prevents its legacy post-dedup guide note from stating
    that promoted copies remain under the corporate annual-report folder.
    """
    def write(package_root, archive_root, documents, env_failures):
        result = original_writer(package_root, archive_root, documents, env_failures)
        readme = Path(archive_root) / '00_자료목록' / 'README_먼저읽기.txt'
        if readme.is_file():
            text = readme.read_text(encoding='utf-8')
            previous = ('4) ENV-INFO가 공식 첨부파일로 제공한 지속가능경영보고서·정책 자료는 원래 '
                        '03 폴더에 보존하면서 04/06에도 사용자 편의를 위해 복사해 표시합니다.')
            corrected = ('4) 04_지속가능경영보고서는 기업 공식 연례보고서 원본 전용입니다. '
                         'ENV-INFO 첨부 원문은 03_환경정보공개시스템/첨부자료_원문에 내용별로 '
                         '보존하며, 원래 사업장·공개연도와 최종 원문 경로는 '
                         '00_자료목록/ENVINFO_첨부자료_참조표.xlsx에서 확인하십시오. '
                         'ENV-INFO의 환경정책 관련 복사본은 06_회사환경정책에 있을 수 있지만 '
                         '공식 연례보고서 확보 건수에 포함되지 않습니다.')
            if previous in text:
                readme.write_text(text.replace(previous, corrected), encoding='utf-8')
        return result
    return write
