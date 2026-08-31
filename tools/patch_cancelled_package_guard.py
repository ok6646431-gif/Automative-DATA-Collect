from pathlib import Path

p=Path('.github/workflows/collect.yml')
text=p.read_text(encoding='utf-8')
old='''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    if: always()\n'''
new='''  package_and_validate:\n    needs: [stable_sources, icis_attempt_1, icis_attempt_2, icis_attempt_3, icis_replay]\n    # Do not build large partial archives for runs superseded by a newer request.\n    # `always()` alone remains true during cancellation and defeats concurrency cancellation.\n    if: ${{ always() && !cancelled() }}\n'''
assert old in text, 'package job condition not found or already patched'
p.write_text(text.replace(old,new,1),encoding='utf-8')
