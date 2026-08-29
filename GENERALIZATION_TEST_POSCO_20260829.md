# POSCO No-Code Generalization Test — 2026-08-29

## Purpose

Test whether the existing enterprise environmental collection/validation pipeline generalizes to POSCO without company-specific runtime code changes.

Target: current steel operating company `주식회사 포스코`.
Requested production scope: 포항제철소 and 광양제철소.

## Why this is a stress test

- The current operating company was newly established by a 2022-03-01 spin-off.
- The pre-spin-off corporation changed its name to `포스코홀딩스 주식회사` and continued as the holding company.
- The current operating company and the pre-spin-off corporation share the historical text `주식회사 포스코`, so name equality must not be treated as legal-entity continuity.
- The requested sites are two very large integrated steelworks with many source-native facility/unit names.

## Test level

**G1 — Discovery/config input allowed; runtime code changes forbidden.**

Allowed interventions:
- replace company Discovery evidence using verified first-party official sources
- encode the verified 2022 spin-off as restructuring context
- replace request-scoped corporate-document declarations using verified official sources
- clear/prevent previous-company event evidence contamination
- change `run_token.txt` only after all other inputs are fixed
- human review of `REVIEW_REQUIRED`

Forbidden interventions after the final run token is committed:
- collector code changes
- orchestrator/runtime code changes
- parser changes
- new POSCO-specific matching logic
- automatic stitching of pre-2022 data into the current legal entity
- weakening validation to force a pass

## Pre-run pass/fail rule

### G1 PASS
The same code reaches a structurally valid package/archive. Individual sources may resolve to `DATA_FOUND`, `NO_DATA`/`NO_MATCH`, `UNAVAILABLE`/remote failure, or `REVIEW_REQUIRED`, provided those states are explicit and do not require a code patch.

### G1 PARTIAL PASS
Core collectors and package complete without code changes, but enrichment/document/history/identity ambiguity requires human review or additional source declarations.

### G1 FAIL
Any runtime/parser/POSCO-specific code patch is required to make the run complete or to prevent incorrect legal-entity/site data from being accepted.

## Fixed Discovery facts

Official POSCO evidence establishes:
- current operating company: `주식회사 포스코`
- spin-off effective date: 2022-03-01
- predecessor corporation continues as `포스코홀딩스 주식회사`
- 포항제철소: 경상북도 포항시 남구 동해안로 6262
- 광양제철소: 전라남도 광양시 폭포사랑길 20-26

The 2022 restructuring is context only. It does not create an alias/identity merge for pre-2022 records.

## Intervention ledger

| Stage | Intervention | Code changed? | Allowed? |
|---|---|---:|---:|
| Test gate | Add this pre-run test definition | No | Yes |
| Discovery | Replace Hyundai Discovery with POSCO official company/site/restructuring evidence | No | Yes |
| Event evidence | Use POSCO request-scoped empty event set | No | Yes |
| Corporate docs | Replace Hyundai documents with verified POSCO official reports/pages | No | Yes |
| Execution | Change run token last | No | Yes |

Test result must be judged against these rules without redefining the criteria after the run.
