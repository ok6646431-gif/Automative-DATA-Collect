import json
from pathlib import Path

from bat_resolver import CATALOG_PATH, resolve
from bat_collector import collect


def run(package,catalog_path=CATALOG_PATH,as_of=None):
    package=Path(package)
    plan=resolve(package,catalog_path,as_of)
    status=collect(package,catalog_path)
    summary={
        'schema_version':'1.0',
        'candidate_count':plan.get('candidate_count',0),
        'site_count':plan.get('site_count',0),
        'collect_catalog_ids':plan.get('collect_catalog_ids',[]),
        'collection_status':status,
        'principle':'Many-to-many site/BAT candidates; current legal applicability, future applicability and technical relevance remain separate.'
    }
    (package/'BAT_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


if __name__=='__main__':
    import argparse
    from datetime import date
    ap=argparse.ArgumentParser(); ap.add_argument('--package',default='assembled'); ap.add_argument('--catalog',default=str(CATALOG_PATH)); ap.add_argument('--as-of',default='')
    a=ap.parse_args(); d=date.fromisoformat(a.as_of) if a.as_of else None
    print(json.dumps(run(a.package,a.catalog,d),ensure_ascii=False,indent=2))
