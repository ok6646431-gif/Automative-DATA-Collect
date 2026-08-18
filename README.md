# Automative-DATA-Collect

Enterprise environmental public-data collection and integration pipeline.

## Master Orchestrator v1.2

Primary collector input contract: `requests/company_profile.json`.

The zero-touch bootstrap input is the versioned Discovery contract in
`requests/company_discovery.schema.json` (see `requests/company_discovery.example.json`).
The external control plane supplies evidence; this repository does not research or
infer corporate facts. Compile it before request generation:

```bash
python orchestrator/company_profile_builder.py requests/company_discovery.json \
  --out requests/company_profile.json \
  --summary Company_Discovery_Summary.json
python orchestrator/request_builder.py requests/company_profile.json \
  --out requests/current.generated.json
```

The compiler preserves raw site/evidence fields, exclusions, restructuring and
unresolved items. It never creates site-address anchors or canonical merges.
Unknown identity remains `REVIEW_REQUIRED`. Annual sources receive independently
derived windows (minimum five years, extended backward when necessary); known full
structured history is preferred. Chemical Statistics receives only explicitly
disclosed survey rounds, while SOOSIRO annual and daily periods stay separate.
Historical aliases retain their active bounds, and generated requests include
per-year search terms so a bounded former name is not queried outside its period.

The profile contains the company name, resolved current/historical legal-name aliases, related-entity exclusions, and source-specific collection windows. In the ChatGPT control-plane workflow the user provides only the company name; company discovery resolves and writes this profile before GitHub Actions execution.

Optional Event evidence contract: `requests/event_evidence.json`.

- Event evidence is collected from official/primary sources by the control plane and supplied to the runtime integration layer.
- If the file is absent, the runtime records `EVENT_DISCOVERY_NOT_RUN`; it does **not** interpret an unperformed/failed search as evidence that no event exists.
- Missing event date, source locator, or strong site identity mapping remains `REVIEW_REQUIRED`.
- Events are context/evidence only. The runtime never makes an automatic causal claim about environmental-value changes.

Execution flow:

1. `orchestrator/request_builder.py` converts the company profile into one standardized five-source request.
2. Stable sources run separately: ENV-INFO, SOOSIRO, CleanSYS.
3. ICIS sources run on a fresh GitHub-hosted runner: PRTR and Chemical Statistics. If the runner cannot reach ICIS, up to two additional fresh-runner attempts are launched sequentially. Retry signaling is separated from workflow failure semantics.
4. `orchestrator/package_run.py` chooses a successful ICIS attempt, assembles the five source outputs, validates raw/detail artifacts, and runs post-collection integration.
5. `orchestrator/postprocess.py` extracts source identities, performs conservative cross-source Identity Resolution, calculates Coverage Status, and populates the Validation Queue.
6. `orchestrator/event_analysis.py` merges verified Event evidence, calculates `Coverage_Event_Links`, and creates a reference-only `Analysis_Ready_Index`.
7. The final package writes the Master Manifest, artifact SHA-256 index, Identity/Coverage/Event outputs, analysis index, and the combined `REVIEW_REQUIRED` queue.

## Runtime safety rules

- Raw source IDs, names, addresses, values, flags, and source artifacts are preserved.
- Different source identities are never auto-merged from name-only or partial-address similarity.
- `0`, null/blank, and `-` remain distinct source-native states.
- SOOSIRO COD and TOC remain separate; provisional/source flags are preserved in raw rows.
- Official totals are never replaced by recalculated totals.
- Chemical Statistics survey rounds are not interpolated into annual observations.
- Collection period and analysis period are separate. Event links may propose segmentation/baseline review but never truncate collected raw data.
- `REVIEW_REQUIRED` is a normal successful automation outcome. Only structural/source-integrity failure makes `package_health=FAIL`.

## Main integration outputs

- `Site_Master.csv`
- `Source_Identity.csv`
- `Coverage_Status.csv`
- `Validation_Queue.csv`
- `Event_Registry.csv`
- `Coverage_Event_Links.csv`
- `Analysis_Ready_Index.csv`
- `Artifact_Index.csv`
- `Master_Manifest.json`
- `REVIEW_REQUIRED.json`

`Analysis_Ready_Index.csv` is intentionally reference-only. It records canonical/source/time keys, raw locators, identity/coverage/comparability state, and event links; it does not copy, normalize, aggregate, or recompute source metrics.
