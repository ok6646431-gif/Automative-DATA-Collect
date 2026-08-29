# Hyundai Motor No-Code Generalization Test — 2026-08-29

## Purpose

Test whether the existing enterprise environmental collection/validation pipeline generalizes to a structurally different company without company-specific code changes.

Target: Hyundai Motor Company / 현대자동차 주식회사
Production scope: Ulsan, Asan, Jeonju factories.

## Test level

**G1 — Discovery/config input allowed; runtime code changes forbidden.**

The current control plane still requires `requests/company_discovery.json`, `requests/document_evidence.json`, and request-scoped event evidence. Therefore this is not a G0 company-name-only test.

Allowed interventions:
- replace company Discovery evidence using first-party official sources
- replace request-scoped corporate-document declarations using verified official sources
- clear/prevent previous-company event evidence contamination
- change `run_token.txt`
- human review of `REVIEW_REQUIRED`

Forbidden interventions after the test starts:
- collector code changes
- orchestrator/runtime code changes
- parser changes
- new company-specific matching logic
- new hard-coded Hyundai exceptions
- weakening validation to force a pass

## Pre-run pass/fail rule

### G1 PASS
The same code reaches a structurally valid package/archive. Individual sources may legitimately resolve to `DATA_FOUND`, `NO_DATA`/`NO_MATCH`, `UNAVAILABLE`/remote failure, or `REVIEW_REQUIRED`, provided those states are explicit and do not require a code patch.

### G1 PARTIAL PASS
Core collectors and package complete without code changes, but enrichment/document/identity ambiguity requires human review or source declarations. This demonstrates reusable core automation but not zero-touch enrichment.

### G1 FAIL
Any runtime/parser/company-specific code patch is required to make the Hyundai run complete or to prevent incorrect company/site data from being accepted.

## Inputs fixed before result

Company Discovery uses only official Hyundai sources for:
- legal/company name
- Ulsan factory: 울산광역시 북구 염포로 700
- Asan factory: 충청남도 아산시 인주면 현대로 1077
- Jeonju factory: 전라북도 완주군 봉동읍 완주산단5로 163

Corporate document input declares five official sustainability reports (2022–2026), the official 2025 environmental-management policy, and the official ESG-policy index.

No automobile BAT document is pre-injected because applicability of the government automobile-parts K-BREF to finished-vehicle plants has not been verified.

No event is pre-seeded.

## Intervention ledger

| Stage | Intervention | Code changed? | Allowed? |
|---|---|---:|---:|
| Discovery | Replace KKPC company discovery with Hyundai official company/site evidence | No | Yes |
| Event evidence | Clear KKPC-specific gaps/events; use Hyundai request-scoped empty event set | No | Yes |
| Corporate docs | Replace KKPC documents with verified Hyundai official reports/policy | No | Yes |
| Execution | Change run token | No | Yes |

Test result will be appended only after the production run completes. Do not redefine the pass criteria after seeing the result.
