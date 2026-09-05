"""Bound legal-name continuity checks to the lifetime of the current legal entity.

Official company history pages can describe predecessor corporations decades before a
newly incorporated spin-off or successor legally existed. Those events are useful
history, but they cannot by themselves become rename obligations of the current entity.
Unknown-date or post-establishment rename signals remain fail-closed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


BLOCKER = "HISTORICAL_LEGAL_NAME_PREDECESSOR_UNRESOLVED"
CURRENT_ALIAS_TYPES = {
    "requested_name", "current_brand_name", "current_alias", "english_legal_name",
    "current_legal_alias",
}


def _year(value: Any) -> int | None:
    m = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def _entity_start_year(discovery: Dict[str, Any], audit: Dict[str, Any]) -> int | None:
    for key in ("legal_entity_active_period", "current_legal_name_active_period"):
        period = discovery.get(key) or {}
        if isinstance(period, dict) and period.get("start_year"):
            try:
                return int(period["start_year"])
            except (TypeError, ValueError):
                pass
    legal = (((audit.get("stages") or {}).get("legal_identity") or {}).get("resolved") or {})
    return _year(legal.get("establishment_date"))


def _signal_year(item: Dict[str, Any]) -> int | None:
    for key in ("year", "date", "effective_date"):
        value = item.get(key)
        year = _year(value)
        if year:
            return year
    period = item.get("effective_period") or {}
    if isinstance(period, dict):
        try:
            return int(period.get("start_year")) if period.get("start_year") else None
        except (TypeError, ValueError):
            return None
    return None


def normalize(discovery: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
    start = _entity_start_year(discovery, audit)
    stage: Dict[str, Any] = {"current_legal_entity_start_year": start}
    audit.setdefault("stages", {})["entity_continuity_policy"] = stage
    if not start:
        stage["status"] = "NOT_APPLICABLE_ENTITY_START_UNKNOWN"
        return discovery

    stages = audit.get("stages") or {}
    official = ((stages.get("official_site") or {}).get("recovery") or {})
    site_signals = [x for x in (official.get("rename_signals") or []) if isinstance(x, dict)]
    kind_signals = [x for x in ((stages.get("kind_disclosure_recovery") or {}).get("rename_disclosures") or []) if isinstance(x, dict)]

    ignored_signals: List[Dict[str, Any]] = []
    relevant_signals: List[Dict[str, Any]] = []
    for source, values in (("OFFICIAL_SITE", site_signals), ("KIND", kind_signals)):
        for item in values:
            year = _signal_year(item)
            record = {"source": source, "year": year, "signal": item}
            if year is not None and year < start:
                ignored_signals.append(record)
            else:
                # Unknown dates remain relevant: fail closed rather than assuming they
                # predate the current corporation.
                relevant_signals.append(record)

    events = list(discovery.get("corporate_restructuring_evidence") or [])
    kept_events: List[Dict[str, Any]] = []
    ignored_events: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "rename":
            kept_events.append(event)
            continue
        year = _signal_year(event)
        if year is not None and year < start:
            ignored_events.append(event)
        else:
            kept_events.append(event)
    discovery["corporate_restructuring_evidence"] = kept_events

    # The current legal name cannot be active before the current legal entity existed.
    current_period = discovery.get("current_legal_name_active_period") or {}
    current_start = None
    if isinstance(current_period, dict):
        try:
            current_start = int(current_period.get("start_year")) if current_period.get("start_year") else None
        except (TypeError, ValueError):
            current_start = None
    if current_start is None or current_start < start:
        discovery["current_legal_name_active_period"] = {"start_year": start}

    for alias in discovery.get("company_aliases", []) or []:
        if not isinstance(alias, dict) or alias.get("alias_type") not in CURRENT_ALIAS_TYPES:
            continue
        period = alias.get("active_period") or {}
        alias_start = None
        if isinstance(period, dict):
            try:
                alias_start = int(period.get("start_year")) if period.get("start_year") else None
            except (TypeError, ValueError):
                alias_start = None
        if alias_start is None or alias_start < start:
            alias["active_period"] = {"start_year": start}

    # Historical names ending before incorporation can be preserved as context, but
    # they must not become automatic collection aliases of the current entity.
    for historical in discovery.get("historical_legal_names", []) or []:
        if not isinstance(historical, dict):
            continue
        period = historical.get("active_period") or {}
        end = None
        if isinstance(period, dict):
            try:
                end = int(period.get("end_year")) if period.get("end_year") else None
            except (TypeError, ValueError):
                end = None
        if end is not None and end < start:
            historical["collection_enabled"] = False
            historical["coverage_role"] = "PRE_ENTITY_HISTORICAL_REFERENCE"

    if not relevant_signals:
        discovery["unresolved_items"] = [
            item for item in (discovery.get("unresolved_items") or [])
            if not (isinstance(item, dict) and item.get("code") == BLOCKER)
        ]
        stage["status"] = "PRE_ENTITY_RENAME_SIGNALS_IGNORED"
    else:
        stage["status"] = "CURRENT_ENTITY_CONTINUITY_SIGNAL_REMAINS"

    stage["ignored_pre_entity_signals"] = ignored_signals
    stage["relevant_signals"] = relevant_signals
    stage["ignored_pre_entity_rename_events"] = ignored_events
    return discovery
