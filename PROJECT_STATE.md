# Environmental Data Platform - Current State

Updated: 2026-09-15 KST
Branch: `run/control-plane`

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

## Current final-candidate shared-code changes

- co-located official units may resolve collection completeness through an evidence-bound `COLOCATED_PUBLIC_REPORTING_SCOPE` relation while `identity_merge=false`
- Human Archive deduplicates the live archive tree before the first full ZIP write
- archive semantic dedup runtime installs `cryptography>=3.1` for encrypted PDFs
- annual-report local-year extraction is boundary-safe: a pre-window report cannot be relabelled as the first requested year
- verified document routes with explicit URL-year conflict cannot override or resolve fresh annual-report coverage
- report finalizer replaces a conflicting primary only with a strong matching-year fallback; otherwise it reopens a blocking gap
- supporting derivatives such as compact books cannot satisfy the full annual sustainability-report route

## Latest strict regression status on final candidate code

### 효성티앤씨 - PASS (1/3)

Discovery run: `34939945165`
Master Orchestrator run: `34940519143` (#240)
Promotion commit: `7e248b0717fe07bd7849c892bb8bb51a8f4fbe01`

Verified:
- Discovery gate = PASS
- sustainability routes 2020-2025 map to `SR_2020` through `SR_2025`
- 2026 = verified non-blocking NOT_PUBLISHED
- Collection Completeness = COMPLETE, 37/37
- Human Archive = COMPLETE
- Application Materials = PASS
- persistent route registry no longer contains the erroneous `SR_2019_en.pdf` mapping for report year 2020

### 금호석유화학 - RUNNING

Strict rerun trigger commit: `d36e31e27712ba96bfb31b1f11ea597363206aa2`
Zero-touch Discovery run: `34942796817`
Current observed state: G0 unit/contract regressions PASS; live Discovery in progress.

### 한화에어로스페이스 - PENDING

Run after the strict Kumho rerun completes. Use the same current shared code and the zero-touch company-name-only path.

## Important invariants

- no company-specific site-name hardcoding
- same address does not imply legal/site identity merge
- collection completeness and identity validation remain separate
- legitimate `REVIEW_REQUIRED` identity items are not cleared merely to make collection green
- raw company-wide collection may be preserved while user archive/analysis are filtered to requested scope

## Known review-only edge case

The requested-scope resolver should eventually be hardened so that selecting only one official unit at a co-located address cannot permit an address-only canonical merge when the company profile already knows a different strongly verified official unit at the same address.

## Next action

1. Finish strict Kumho rerun and verify Collection / Human Archive / Application Materials.
2. Run strict Hanwha Aerospace rerun on the same shared code.
3. When all three representative regressions pass, start the new-company 3-consecutive acceptance gate.
