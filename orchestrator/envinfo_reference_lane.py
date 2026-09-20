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
