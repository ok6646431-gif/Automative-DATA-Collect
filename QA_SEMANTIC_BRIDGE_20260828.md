# Semantic Bridge QA — 2026-08-28

## Purpose

This note records a manual semantic QA that found a gap between **formal four-layer traceability** and **topic-level semantic coherence**. It is evidence for the project QA history, not an environmental performance judgment.

The review used KKPC (`금호석유화학주식회사`) actual collected evidence. Before this QA, five topics were formally classified `FOUR_LAYER_READY` because each broad environmental domain had:

1. `OBSERVED`
2. `COMPANY_ACTION`
3. `INDUSTRY_TECHNICAL`
4. `FUTURE_DIRECTION`

Manual review showed that four of those five topics did not have a defensible bridge across the **same observed environmental subtopic**.

## Actual-data QA inputs

Fresh-path package QA combined:

- verified stable-source artifact from Master Run #121 (`33178406275`)
- fresh ICIS artifact from Master Run #122 (`33181052754`)
- current `run/control-plane` semantic-bridge code

Regression suite result: **132 tests passed**.

Actual package result:

- `package_health`: `PASS`
- `validation`: `REVIEW_REQUIRED`
- ICIS selection: `GOOD_ATTEMPT`
- replayed ICIS sources: `[]`
- documents processed: 13
- pages scanned: 1,224
- semantic candidates: 2,703
- generated industry facts: 1,563
- document semantic failures: 0
- review candidates: 31
- `FOUR_LAYER_READY`: **1**
- `MULTI_LAYER_REVIEW`: **24**
- `semantic_bridge_ready`: **1**
- `semantic_bridge_blocked`: **4**

QA workflow run: `33183267684` (`Fresh package live QA`, temporary workflow subsequently removed).

## Five formally READY topics reviewed

### 1. 여수제1에너지 — AIR

**Decision: keep `FOUR_LAYER_READY`.**

Observed evidence includes a NOx signal. Company action includes a same-site SCR investment explicitly for boiler NOx reduction. The verified Energy K-BREF contains page-grounded NOx/SCR technical context, and company future-direction evidence explicitly addresses air-pollutant management/targets.

The semantic bridge therefore resolves on anchor:

- `NOX`

This is still **not causal proof**. Production, flue-gas flow, operating time, source composition, permit limits and other denominators remain necessary before judging environmental performance or attributing the measured change to SCR.

### 2. 여수제2에너지 — AIR

**Decision: downgrade to `MULTI_LAYER_REVIEW`.**

Observed anchors:

- `NOX`
- `SOX`

The same-site company action that previously satisfied the broad AIR layer was a urea-production control facility described as an absorption facility for **ammonia and dust** reduction. That action does not establish a same-topic bridge to the observed NOx/SOx signals.

New bridge state:

- `NO_COMMON_TOPIC_BRIDGE`
- missing semantic bridge: company action for NOx/SOx

### 3. 여수제2에너지 — WATER

**Decision: downgrade to `MULTI_LAYER_REVIEW`.**

Observed anchors:

- `SS`
- `TN`
- `TOC`

The company action that previously filled this topic was again the urea-process **ammonia/dust air-control facility**. It is not a same-topic water-management action.

New bridge state:

- `NO_COMMON_TOPIC_BRIDGE`
- missing semantic bridge: company action for SS/TN/TOC

### 4. 여수제1에너지 — CHEMICALS

**Decision: downgrade to `MULTI_LAYER_REVIEW`.**

Observed evidence is an aggregate `CHEMICAL_RELEASE_TOTAL` signal. Public action/reference/future evidence exists for chemical management, but the observed aggregate does not identify which substance or substances drove the change.

New bridge state:

- `CHEMICAL_AGGREGATE_DRIVER_REQUIRED`

A substance-level observed driver is required before an action or BAT/reference statement can be meaningfully connected to the aggregate PRTR change.

### 5. 여수제2에너지 — CHEMICALS

**Decision: downgrade to `MULTI_LAYER_REVIEW`.**

Same issue as 여수제1에너지: aggregate chemical-release change exists, but no substance-level driver is established in the observed layer.

New bridge state:

- `CHEMICAL_AGGREGATE_DRIVER_REQUIRED`

## Root cause

The prior cross-layer readiness rule matched evidence primarily by:

- broad environmental domain (`AIR`, `WATER`, `CHEMICALS`, etc.)
- canonical site scope
- existence of the four independent evidence layers

This was appropriate for discovery and traceability, but too permissive for a final `FOUR_LAYER_READY` label. Evidence can belong to the same broad domain while addressing different pollutants, processes or controls.

Example: `NOx/SOx observed` + `ammonia/dust absorption action` are both AIR evidence, but they do not establish one coherent review chain.

## New fail-closed rule

`FOUR_LAYER_READY` now requires both:

1. all four evidence layers are present, **and**
2. at least one observed subtopic has a topic-level semantic bridge across:
   - observed metric/subtopic
   - same-site company action
   - page-grounded industry technical evidence
   - future-direction evidence

Current observed-anchor families include examples such as:

- AIR: NOX, SOX, DUST, VOC, HCL, HF, CO
- WATER: SS, TN, TP, TOC, COD, BOD
- WATER_RESOURCES: water use / water reuse
- GHG_ENERGY: GHG / energy
- WASTE: waste / recycling
- CHEMICALS: recognized substance-level anchors

For CHEMICALS, aggregate release/transfer totals are explicitly **fail-closed** until a substance-level driver is identified.

If four broad layers exist but the bridge fails, the topic remains reviewable but is downgraded and a concrete study question is generated:

- `TOPIC_SEMANTIC_BRIDGE_GAP`, or
- `CHEMICAL_DRIVER_GAP`

## Interpretation boundary

The semantic bridge is a **review-readiness rule**, not a causal model.

Even a `FOUR_LAYER_READY` topic means only that the evidence is coherent enough for a human to study further. It does not establish:

- environmental performance improvement/deterioration
- legal compliance/non-compliance
- risk ranking
- BAT implementation by the company
- causal impact of a company investment on the observed metric

Those judgments still require the relevant denominators, process/operating context, site-specific applicability and legal/permit evidence.
