# Environmental Data Platform - Current State

Updated: 2026-09-15 KST
Branch: `run/control-plane`
Shared-code candidate: `fa5c2607a94440386580c98e81b437d5fe559d38`

## Acceptance protocol

A representative regression company passes only when all of the following are verified from the current shared code:

1. Collection Completeness = `COMPLETE`
2. Human Archive = `COMPLETE/PASS`
3. Application Materials = `PASS`

If shared/common code changes, representative regressions must be rerun on the new final candidate code before starting the new-company consecutive acceptance gate.

Representative regression companies:
- 금호석유화학
- 한화에어로스페이스
- 효성티앤씨

## Current shared-code changes

- co-located official units may resolve collection completeness through an evidence-bound `COLOCATED_PUBLIC_REPORTING_SCOPE` relation while `identity_merge=false`
- Human Archive deduplicates the live archive tree before the first full ZIP write
- archive semantic dedup runtime installs `cryptography>=3.1` for encrypted PDFs
- annual-report local-year extraction is boundary-safe: a pre-window report cannot be relabelled as the first requested year
- verified document routes with explicit URL-year conflict cannot override or resolve fresh annual-report coverage
- report finalizer replaces a conflicting primary only with a strong matching-year fallback; otherwise it reopens a blocking gap
- supporting derivatives such as compact books cannot satisfy the full annual sustainability-report route
- **company-wide collector raw evidence is now physically separated from the Human Archive**
  - collector raw remains under package `output` and in source/final workflow artifacts
  - `Human_Archive.zip` must not contain `90_시스템원본`
  - production archive stage fails closed if system/raw files leak into the Human Archive
  - Human Archive contains requested-scope human-facing material, indexes and BAT/reference area only

Raw-separation shared commits:
- `17255bbf4fd2536a9a5e0609036d3e60f848a141` - add external raw-preservation policy helper
- `4f22dae0d6f42dea6bb2643795d9af1cc975886d` - exclude collector raw from production Human Archive
- `71063e10e5794fdc1e8b3e01a7a7fc338b4f24da` - archive contract 2.2 / external raw-preservation contract
- `fa5c2607a94440386580c98e81b437d5fe559d38` - raw-separation regression tests

## POSCO raw-separation validation

Purpose: validate the archive-boundary change using the exact same verified POSCO source artifacts from the pre-fix run, so any size/result difference is attributable to archive packaging rather than source collection.

Pre-fix POSCO Master run: `34947350725`
Pre-fix result:
- Collection Completeness = COMPLETE, 82/82
- Human Archive = COMPLETE/PASS
- Application Materials = PASS
- Human Archive internal ZIP size = `1,045,193,086` bytes
- system/raw files inside Human Archive = 752

Corrected package replay:
- branch: `run/posco-raw-separation-test`
- workflow run: `34961228811`
- job: `104355032706`
- input source artifacts: reused unchanged from pre-fix POSCO run `34947350725`
- result = SUCCESS

Verified corrected result:
- package health = PASS
- Collection Completeness = COMPLETE, 82/82
- Human Archive = COMPLETE/PASS
- Application Materials = PASS
- Human Archive internal ZIP size = `185,355,678` bytes
- Human Archive files = 54
- Human Archive system/raw files = 0
- `system_raw_absent_from_human_archive = true`
- raw collector evidence still preserved externally:
  - raw files = 752
  - raw bytes = `1,208,467,074`
  - package raw root = `output`
  - `preserved_in_final_package = true`
- Application Materials = PASS with existing `NO_SYSTEM_ORIGINALS`, scope and ENV-INFO integrity checks
- corrected Human Archive artifact ID = `10393661642`
- corrected Application Materials artifact ID = `10394065141`

Size effect with identical source inputs:
- `1,045,193,086` -> `185,355,678` bytes
- reduction = `859,837,408` bytes (~82.3%)

Conclusion: the previous ~1 GB Human Archive was caused by duplicating the broad collector raw tree into the human-facing ZIP. The fix preserves raw evidence for audit/reproduction without delivering it inside Human Archive.

## Strict representative regression status after raw-separation change

**RESET: 0/3 on the new shared-code candidate.**

The POSCO replay validates the new archive boundary but POSCO is not one of the three strict representative regression companies. Historical representative PASS results remain useful evidence but do not count toward the post-change strict suite.

Historical checkpoints before this common-code change:
- 효성티앤씨: PASS on run `34940519143`
- 금호석유화학: prior strict work existed and later promotion was present on the branch, but must be rerun on the new candidate
- 한화에어로스페이스: pending before the reset

Required new strict sequence on unchanged shared code:
1. 금호석유화학
2. 한화에어로스페이스
3. 효성티앤씨

Each must independently verify:
- Collection Completeness = COMPLETE
- Human Archive = COMPLETE/PASS
- Application Materials = PASS
- `system_raw_absent_from_human_archive = true`
- company-wide raw evidence remains externally preserved

## Important invariants

- no company-specific site-name hardcoding
- same address does not imply legal/site identity merge
- collection completeness and identity validation remain separate
- legitimate `REVIEW_REQUIRED` identity items are not cleared merely to make collection green
- company-wide raw collection may be preserved while user archive/analysis are filtered to requested scope
- raw preservation and human delivery are separate physical products: raw stays in package/source artifacts, never in `Human_Archive.zip`

## Known review-only edge case

The requested-scope resolver should eventually be hardened so that selecting only one official unit at a co-located address cannot permit an address-only canonical merge when the company profile already knows a different strongly verified official unit at the same address.

## Next action

1. Rerun strict 금호석유화학 on shared candidate `fa5c260...` (or later code-identical candidate) and verify all archive/raw-separation gates.
2. Rerun 한화에어로스페이스 on exactly the same shared code.
3. Rerun 효성티앤씨 on exactly the same shared code.
4. Only after 3/3 PASS, start the new-company 3-consecutive acceptance gate.
