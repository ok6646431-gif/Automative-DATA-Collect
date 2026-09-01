from pathlib import Path

WORKFLOW = Path('.github/workflows/collect.yml')


def validate(text: str) -> None:
    stable_start = text.index('  stable_sources:\n')
    corp_start = text.index('  corporate_documents:\n')
    icis_start = text.index('  icis_attempt_1:\n')
    stable_block = text[stable_start:corp_start]
    corp_block = text[corp_start:icis_start]

    checks = {
        'corporate collector removed from stable_sources': 'Collect corporate documents' not in stable_block,
        'public stable artifact renamed': 'name: stable-public-sources' in stable_block,
        'corporate collector has its own job': 'python collectors/corporate_docs_collect.py' in corp_block,
        'corporate artifact exists': 'name: stable-corporate-documents' in corp_block,
        'packaging waits for both stable jobs': 'needs: [stable_sources, corporate_documents, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]' in text,
        'packaging downloads both stable artifacts': 'pattern: stable-*' in text and 'merge-multiple: true' in text,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit('split orchestrator validation failed: ' + '; '.join(failed))


def main() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')

    # Idempotent: if the split job already exists, only validate the final structure.
    if '  corporate_documents:\n' in text:
        validate(text)
        print('collect.yml already uses split stable/corporate jobs')
        return

    start = text.index('  stable_sources:\n')
    end = text.index('  icis_attempt_1:\n', start)

    split_block = '''  stable_sources:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: python -m pip install --disable-pip-version-check requests beautifulsoup4 xlsxwriter
      - name: Bootstrap runtime company inputs
        run: >-
          python orchestrator/bootstrap_inputs.py
          --profile-out requests/runtime/company_profile.generated.json
          --request-out requests/current.generated.json
          --summary-out requests/runtime/Company_Discovery_Summary.json
      - name: Run parser regression tests
        run: python -m unittest discover -s tests -p 'test_*.py' -v
      - name: Collect ENV-INFO
        continue-on-error: true
        run: python collectors/envinfo_collect.py requests/current.generated.json
      - name: Recover and deduplicate ENV-INFO attachments
        continue-on-error: true
        run: python collectors/envinfo_attachment_recovery.py --out output/ENVINFO --repo-root .
      - name: Collect SOOSIRO
        continue-on-error: true
        run: python collectors/soosiro_collect.py requests/current.generated.json
      - name: Collect CleanSYS
        continue-on-error: true
        run: python collectors/cleansys_collect.py requests/current.generated.json
      - name: Upload stable public sources
        if: ${{ always() && cancelled() == false }}
        uses: actions/upload-artifact@v4
        with:
          name: stable-public-sources
          path: output/
          if-no-files-found: warn
          retention-days: 7

  corporate_documents:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install document dependencies
        run: python -m pip install --disable-pip-version-check requests beautifulsoup4
      - name: Bootstrap runtime company inputs
        run: >-
          python orchestrator/bootstrap_inputs.py
          --profile-out requests/runtime/company_profile.generated.json
          --request-out requests/current.generated.json
          --summary-out requests/runtime/Company_Discovery_Summary.json
      - name: Collect corporate documents
        continue-on-error: true
        run: python collectors/corporate_docs_collect.py requests/document_evidence.json requests/runtime/company_profile.generated.json
      - name: Upload stable corporate documents
        if: ${{ always() && cancelled() == false }}
        uses: actions/upload-artifact@v4
        with:
          name: stable-corporate-documents
          path: output/
          if-no-files-found: warn
          retention-days: 7

'''

    text = text[:start] + split_block + text[end:]

    old_needs = '    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n'
    new_needs = '    needs: [stable_sources, corporate_documents, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n'
    if old_needs not in text:
        raise SystemExit('package_and_validate needs anchor not found')
    text = text.replace(old_needs, new_needs, 1)

    old_download = '''      - name: Download stable artifact
        continue-on-error: true
        uses: actions/download-artifact@v4
        with:
          name: stable-sources
          path: collected/stable
'''
    new_download = '''      - name: Download stable artifacts
        continue-on-error: true
        uses: actions/download-artifact@v4
        with:
          pattern: stable-*
          path: collected/stable
          merge-multiple: true
'''
    if old_download not in text:
        raise SystemExit('stable artifact download anchor not found')
    text = text.replace(old_download, new_download, 1)

    validate(text)
    WORKFLOW.write_text(text, encoding='utf-8')
    print('Split public stable sources and corporate documents into independent jobs')


if __name__ == '__main__':
    main()
