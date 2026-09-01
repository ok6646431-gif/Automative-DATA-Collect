# Automative-DATA-Collect

Enterprise environmental public-data collection, document archiving, and integration pipeline.

## Master Orchestrator + Archive v1

Zero-touch control-plane input starts with `requests/company_discovery.json`, using the
versioned contract in `requests/company_discovery.schema.json`. The external control
plane supplies verified company, Event, and corporate-document evidence; the repository
does not invent or weakly infer corporate facts.

GitHub Actions routes company input through `orchestrator/bootstrap_inputs.py`. When
`requests/company_discovery.json` exists it is preferred and compiled into an ephemeral
runtime profile plus the standardized collector request. The tracked
`requests/company_profile.json` remains only a compatibility fallback for proof runs and
recovery; bootstrap never overwrites it.

### Persistent control-plane execution branch

Production-style ChatGPT control-plane runs use the persistent `run/control-plane`
branch. A push to that branch triggers the orchestrator when any of these execution
inputs changes:

- `requests/company_discovery.json`
- `requests/event_evidence.json`
- `requests/document_evidence.json`
- `requests/run_token.txt`

This removes the need to open or merge a pull request for each company run. The control
plane keeps the branch synchronized with current `main`, writes validated Discovery /
Event / Document evidence, advances `run_token.txt` when an explicit rerun is needed,
and associates the resulting Actions run and final artifact with that exact commit SHA.
Execution-only evidence files are not merged into `main`.

Pull-request CI remains available for code changes. `workflow_dispatch` remains available
for manual recovery.

Local/runtime bootstrap equivalent:

```bash
python orchestrator/bootstrap_inputs.py \
  --profile-out requests/runtime/company_profile.generated.json \
  --request-out requests/current.generated.json \
  --summary-out requests/runtime/Company_Discovery_Summary.json
```

The compiler preserves raw site/evidence fields, exclusions, restructuring and unresolved
items. It never creates site-address anchors or canonical merges. Unknown identity remains
`REVIEW_REQUIRED`. Annual sources receive independently derived windows (minimum five
years, extended backward when necessary); known full structured history is preferred.
Chemical Statistics receives only explicitly disclosed survey rounds, while SOOSIRO
annual and daily periods remain separate. Historical aliases retain their active bounds,
and generated requests include per-year search terms so a bounded former name is not
queried outside its known period.

### Corporate document evidence

Optional corporate-document evidence uses `requests/document_evidence.json` and the
versioned schema `requests/document_evidence.schema.json`.

The control plane may register verified official documents such as:

- multi-year Sustainability / ESG reports,
- annual reports and environmental disclosures,
- environmental, SHE, chemical, climate and energy policies,
- corporate restructuring evidence,
- BAT / regulatory / industry guidelines,
- other official environmental documents.

The document lane is request-scoped. A stale or mismatched `request_id` fails closed and
is never applied to another company. Only verified `http(s)` evidence is downloaded.
Executable and script payloads are prohibited, and per-file / per-run size safety limits
are enforced. Raw document filename, URL/locator, retrieval time, bytes, SHA-256,
content type and collection status are preserved.

### ENV-INFO attachment archive

ENV-INFO collection now goes beyond search rows and detail HTML. Every publicly exposed
attachment link on collected company/site detail pages is discovered and, when accessible,
downloaded before any importance filtering. This includes files such as organization
charts, environment/SHE roles and responsibilities, internal-audit records, environmental
goals and policies, emergency-response materials, chemical-management material, training
records and evidence-only attachments.

Attachments keep their source-native file ID, original filename, company/site, disclosure
year, disclosure section, source locator, bytes, SHA-256, content type and download
status. Importance (`CORE`, `SUPPORTING`, `EVIDENCE_ONLY`) is only a post-acquisition
classification layer; it never determines whether a public attachment is collected.
Failed public attachments remain explicit `REVIEW_REQUIRED` items rather than silently
disappearing.

### Human-facing Archive v1

After the proven structured-data package completes, `orchestrator/archive_stage.py`
builds a user-facing archive modeled on a normal Windows company-environment folder.
The internal raw package remains the audit/source-of-truth layer; the human archive is a
classified copy for practical research use.

Primary folders:

```text
{회사명}_환경자료/
├─ 00_자료목록/
├─ 01_TMS/
│  ├─ 대기_CleanSYS/
│  └─ 수질_SOOSIRO/
├─ 02_화학물질/
│  ├─ PRTR_배출이동량/
│  └─ 화학물질통계/
├─ 03_환경정보공개시스템/
├─ 04_지속가능경영보고서/
├─ 05_사업보고서_공시/
├─ 06_회사환경정책/
└─ 07_가이드라인_참고자료/
```

ENV-INFO attachments are stored once under business-site / year / semantic category to
avoid duplicate multi-hundred-MB archives. `00_자료목록/핵심자료_목록.csv` identifies
CORE material without making a second physical copy.

Archive indexes include:

- `Document_Index.csv`
- `핵심자료_목록.csv`
- `Source_Coverage.csv`
- `Archive_File_Index.csv`
- `Archive_Manifest.json`
- the existing Identity / Coverage / Event / Review integration files.

The final GitHub artifact contains the validated core package plus a single compact
`Human_Archive.zip`. `Archive_Summary.json` records the archive file count, ZIP bytes and
SHA-256. Missing, blocked, unverified or ambiguous document coverage is recorded as a
review/gap state; it is never silently interpreted as evidence that no document exists.

### Final user delivery

GitHub Actions artifacts remain the internal, expiring handoff between collection and
packaging jobs. Final user-facing packages are published as GitHub Release assets instead
of being split into chat-sized chunks. One company normally produces one
`{회사명}_지원용_환경자료.zip`; only a package that exceeds GitHub's per-asset limit is
split at meaningful archive-folder boundaries.

`requests/release_delivery.json` is the control-plane request for this final delivery
stage. A push that changes the request validates the source Actions run, downloads the
declared application-package artifacts, verifies ZIP integrity, generates SHA-256
checksums and creates or updates the requested GitHub Release. Re-running the same tag is
idempotent: matching asset names are replaced rather than duplicated.

### Event evidence

Optional Event evidence contract: `requests/event_evidence.json`.

- Event evidence is collected from official/primary sources by the control plane and
  supplied to the runtime integration layer.
- If the file is absent, runtime records `EVENT_DISCOVERY_NOT_RUN`; it does **not**
  interpret an unperformed or failed search as evidence that no event exists.
- Missing event date, source locator, or strong site identity mapping remains
  `REVIEW_REQUIRED`.
- Events are context/evidence only. Runtime never makes an automatic causal claim about
  environmental-value changes.

## Execution flow

1. `orchestrator/bootstrap_inputs.py` prefers validated Company Discovery evidence,
   compiles a runtime company profile, and creates one standardized five-source request.
2. Stable structured sources run: ENV-INFO (including detail attachments), SOOSIRO and
   CleanSYS; the request-scoped corporate document lane runs alongside them.
3. ICIS sources run on fresh GitHub-hosted runners: PRTR and Chemical Statistics. If a
   runner cannot reach ICIS, up to two additional fresh-runner attempts are launched.
4. `orchestrator/package_run.py` chooses a successful ICIS attempt, assembles the five
   structured source outputs and validates raw/detail artifacts.
5. `orchestrator/postprocess.py` performs conservative cross-source Identity Resolution,
   calculates Coverage Status and populates the Validation Queue.
6. `orchestrator/event_analysis.py` merges verified Event evidence, calculates
   `Coverage_Event_Links`, and creates a reference-only `Analysis_Ready_Index`.
7. `orchestrator/archive_stage.py` integrates the corporate-document lane, adds archive
   coverage/review states, and builds the human-facing environmental archive ZIP.
8. The final package contains the generated Company Profile, Discovery summary, Master
   Manifest, artifact hashes, Identity/Coverage/Event outputs, combined
   `REVIEW_REQUIRED`, corporate-document metadata and `Human_Archive.zip`.

## Runtime safety rules

- Raw source IDs, names, addresses, values, flags and source artifacts are preserved.
- Different source identities are never auto-merged from name-only or partial-address
  similarity.
- `0`, null/blank and `-` remain distinct source-native states.
- SOOSIRO COD and TOC remain separate; provisional/source flags remain raw.
- Official totals are never replaced by recalculated totals.
- Chemical Statistics survey rounds are not interpolated into annual observations.
- Collection period and analysis period are separate. Event links may propose
  segmentation/baseline review but never truncate collected raw data.
- Public ENV-INFO attachments are collected before importance classification.
- Corporate document downloads require request scope + verified evidence; executable /
  script payloads are prohibited.
- `REVIEW_REQUIRED` is a normal successful automation outcome. Only structural/source
  integrity failure makes `package_health=FAIL`.

## Main integration outputs

- `Company_Profile.json`
- `Company_Discovery_Summary.json`
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
- `Archive_Summary.json`
- `Human_Archive.zip`

`Analysis_Ready_Index.csv` is intentionally reference-only. It records
canonical/source/time keys, raw locators, identity/coverage/comparability state and Event
links; it does not copy, normalize, aggregate or recompute source metrics.
