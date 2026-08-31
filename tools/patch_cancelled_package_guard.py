from pathlib import Path

p = Path('.github/workflows/collect.yml')
text = p.read_text(encoding='utf-8')
old = '''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    if: always()\n'''
preferred = '''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    # Do not build large partial archives for runs superseded by a newer request.\n    # `always()` alone remains true during cancellation and defeats concurrency cancellation.\n    if: ${{ always() && !cancelled() }}\n'''
safe_markers = (
    'if: ${{ always() && !cancelled() }}',
    'if: ${{ always() && cancelled() == false }}',
)

if any(marker in text for marker in safe_markers):
    print('Cancellation guard already present; no patch required.')
elif old in text:
    p.write_text(text.replace(old, preferred, 1), encoding='utf-8')
    print('Cancellation guard patched.')
else:
    raise SystemExit('package job condition not found and no safe cancellation guard detected')
