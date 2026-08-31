from pathlib import Path

p = Path('.github/workflows/collect.yml')
text = p.read_text(encoding='utf-8')
old = '''  stable_sources:\n    runs-on: ubuntu-latest\n    timeout-minutes: 45\n'''
new = '''  stable_sources:\n    runs-on: ubuntu-latest\n    timeout-minutes: 60\n'''
assert old in text, 'stable source timeout block not found'
text = text.replace(old, new, 1)
old = '''      - name: Upload stable sources\n        if: always()\n'''
new = '''      - name: Upload stable sources\n        if: ${{ always() && cancelled() == false }}\n'''
assert old in text, 'stable upload condition not found'
text = text.replace(old, new, 1)
old = '''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    if: always()\n'''
new = '''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    # A superseded request is intentionally cancelled by the concurrency group.\n    # Do not turn that cancellation into a large partial archive build.\n    if: ${{ always() && cancelled() == false }}\n'''
assert old in text, 'package condition not found'
text = text.replace(old, new, 1)
assert text.count('cancelled() == false') >= 2
p.write_text(text, encoding='utf-8')
