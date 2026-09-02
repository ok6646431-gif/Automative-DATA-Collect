from pathlib import Path


path = Path('.github/workflows/collect.yml')
text = path.read_text(encoding='utf-8')

old_timeout = """  package_and_validate:
    needs: [stable_sources, corporate_documents, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]
    # A superseded request is intentionally cancelled by the concurrency group.
    # Do not turn that cancellation into a large partial archive build.
    if: ${{ always() && cancelled() == false && needs.stable_sources.result == 'success' && needs.corporate_documents.result == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 20
"""
new_timeout = old_timeout.replace('timeout-minutes: 20', 'timeout-minutes: 30')
if old_timeout in text:
    text = text.replace(old_timeout, new_timeout, 1)
elif new_timeout not in text:
    raise RuntimeError('package_and_validate timeout anchor not found')

anchor = """      - name: Upload human-facing archive
        id: human_archive_upload
        if: ${{ always() && hashFiles('assembled/Human_Archive.zip') != '' }}
        uses: actions/upload-artifact@v4
        with:
          name: enterprise-env-human-archive
          path: assembled/Human_Archive.zip
          if-no-files-found: warn
          retention-days: 14
      - name: Prepare lightweight metadata delivery
"""
replacement = """      - name: Upload human-facing archive
        id: human_archive_upload
        if: ${{ always() && hashFiles('assembled/Human_Archive.zip') != '' }}
        uses: actions/upload-artifact@v4
        with:
          name: enterprise-env-human-archive
          path: assembled/Human_Archive.zip
          if-no-files-found: warn
          retention-days: 14
      - name: Build and validate application materials
        if: ${{ hashFiles('assembled/Human_Archive.zip') != '' }}
        run: >-
          python tools/build_application_material_from_archive.py
          --input assembled/Human_Archive.zip
          --output-dir application-delivery
          --source-run ${{ github.run_id }}
          --summary-out application-delivery/application_package_result.json
      - name: Upload application materials
        id: application_upload
        if: ${{ always() && hashFiles('application-delivery/*.zip') != '' }}
        uses: actions/upload-artifact@v4
        with:
          name: enterprise-env-application-materials
          path: application-delivery/
          if-no-files-found: error
          retention-days: 14
          compression-level: 0
      - name: Prepare lightweight metadata delivery
"""
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif 'name: Build and validate application materials' not in text:
    raise RuntimeError('human archive upload anchor not found')

env_anchor = """          HUMAN_ARTIFACT_ID: ${{ steps.human_archive_upload.outputs.artifact-id }}
          METADATA_ARTIFACT_ID: ${{ steps.metadata_upload.outputs.artifact-id }}
"""
env_replacement = """          HUMAN_ARTIFACT_ID: ${{ steps.human_archive_upload.outputs.artifact-id }}
          APPLICATION_ARTIFACT_ID: ${{ steps.application_upload.outputs.artifact-id }}
          METADATA_ARTIFACT_ID: ${{ steps.metadata_upload.outputs.artifact-id }}
"""
if env_anchor in text:
    text = text.replace(env_anchor, env_replacement, 1)
elif 'APPLICATION_ARTIFACT_ID:' not in text:
    raise RuntimeError('receipt env anchor not found')

receipt_anchor = """          human_id=os.environ.get(\"HUMAN_ARTIFACT_ID\",\"\")
          metadata_id=os.environ.get(\"METADATA_ARTIFACT_ID\",\"\")
          description=f\"run #{run_number} {state}\"
          if artifact_id:
              description += f\"; final {artifact_id}\"
          if human_id:
              description += f\"; human {human_id}\"
          if metadata_id:
              description += f\"; meta {metadata_id}\"
"""
receipt_replacement = """          human_id=os.environ.get(\"HUMAN_ARTIFACT_ID\",\"\")
          application_id=os.environ.get(\"APPLICATION_ARTIFACT_ID\",\"\")
          metadata_id=os.environ.get(\"METADATA_ARTIFACT_ID\",\"\")
          description=f\"run #{run_number} {state}\"
          if artifact_id:
              description += f\"; final {artifact_id}\"
          if human_id:
              description += f\"; human {human_id}\"
          if application_id:
              description += f\"; app {application_id}\"
          if metadata_id:
              description += f\"; meta {metadata_id}\"
"""
if receipt_anchor in text:
    text = text.replace(receipt_anchor, receipt_replacement, 1)
elif 'application_id=os.environ.get("APPLICATION_ARTIFACT_ID","")' not in text:
    raise RuntimeError('receipt body anchor not found')

path.write_text(text, encoding='utf-8')
