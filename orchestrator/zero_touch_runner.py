"""Runtime entry point wiring version-tolerant public adapters into G0."""

from __future__ import annotations

import sys
from pathlib import Path

# When invoked as ``python orchestrator/zero_touch_runner.py`` Python places the
# orchestrator directory, not the repository root, on sys.path.  Add the root so the
# same imports work in Actions and in ``python -m``/unit-test execution.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import dart_public_resolver
from orchestrator import g0_evidence_enrichment
from orchestrator import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys
zero_touch_discovery.discover_site_candidates = g0_evidence_enrichment.discover_site_candidates
zero_touch_discovery._extract_rename_date_and_names = g0_evidence_enrichment.extract_rename_date_and_names

_base_discover = zero_touch_discovery.discover


def _enriched_discover(company: str, start_year: int = 2020, max_pages: int = 90):
    discovery, documents, audit = _base_discover(company, start_year=start_year, max_pages=max_pages)
    return g0_evidence_enrichment.enrich_discovery_from_audit(discovery, documents, audit)


zero_touch_discovery.discover = _enriched_discover

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
