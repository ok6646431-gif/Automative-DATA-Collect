# Automative-DATA-Collect

Enterprise environmental public-data collection pipeline.

## Master Orchestrator v1.0

Input contract: `requests/company_profile.json`.

The profile contains the company name, resolved current/historical legal-name aliases, entity exclusions, and source-specific collection windows. In the ChatGPT workflow the user only provides the company name; company resolution populates this profile before execution.

Execution flow:

1. `orchestrator/request_builder.py` converts the company profile into one standardized five-source request.
2. Stable sources run separately: ENV-INFO, SOOSIRO, CleanSYS.
3. ICIS sources run on a fresh GitHub-hosted runner: PRTR and Chemical Statistics. If the runner cannot reach ICIS, up to two additional fresh-runner attempts are launched sequentially.
4. `orchestrator/package_run.py` chooses the successful ICIS attempt, assembles the five source outputs, validates detail/raw artifacts, calculates SHA-256 hashes, and writes the Master Manifest, Coverage Matrix, Artifact Index, and REVIEW_REQUIRED queue.

Source-level `NO_MATCH`, short coverage, and identity review are represented explicitly and are not treated as equivalent to collector failure.
