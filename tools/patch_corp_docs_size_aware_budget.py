from pathlib import Path

p=Path('collectors/corporate_docs_collect.py')
text=p.read_text(encoding='utf-8')
old='''DOWNLOAD_ATTEMPTS = 2\nPREFLIGHT_TIMEOUT = (5, 10)\nDOWNLOAD_TIMEOUT = (8, 25)\nATTACHMENT_DISCOVERY_TIMEOUT = (15, 30)\n# requests' read timeout is an inactivity timeout, not a total transfer deadline.\n# Bound each source candidate so slow-drip servers cannot monopolize a workflow.\nMAX_DOCUMENT_WALL_SECONDS = 120.0\n'''
new='''DOWNLOAD_ATTEMPTS = 2\nPREFLIGHT_TIMEOUT = (8, 15)\nDOWNLOAD_TIMEOUT = (15, 60)\nATTACHMENT_DISCOVERY_TIMEOUT = (20, 60)\n# requests' read timeout is only an inactivity timeout. Keep a short default\n# wall budget for ordinary files, but give legitimately large official files a\n# size-aware allowance while retaining an absolute upper bound.\nBASE_DOCUMENT_WALL_SECONDS = 120.0\nMAX_DOCUMENT_WALL_SECONDS = 360.0\nMIN_EXPECTED_TRANSFER_BPS = 128 * 1024\nLARGE_FILE_OVERHEAD_SECONDS = 30.0\n'''
assert old in text, 'corporate timeout constants not found'
text=text.replace(old,new,1)
old='''def download_one(session, doc, target, total_bytes):\n    url = str(doc.get("source_url") or "")\n    headers = preflight(session, doc, url)\n    last_exc = None\n    deadline = time.monotonic() + MAX_DOCUMENT_WALL_SECONDS\n    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):\n'''
new='''def wall_budget_for_length(length):\n    if not length:\n        return BASE_DOCUMENT_WALL_SECONDS\n    estimated = LARGE_FILE_OVERHEAD_SECONDS + (float(length) / float(MIN_EXPECTED_TRANSFER_BPS))\n    return min(MAX_DOCUMENT_WALL_SECONDS, max(BASE_DOCUMENT_WALL_SECONDS, estimated))\n\n\ndef download_one(session, doc, target, total_bytes):\n    url = str(doc.get("source_url") or "")\n    headers = preflight(session, doc, url)\n    last_exc = None\n    started = time.monotonic()\n    deadline = started + BASE_DOCUMENT_WALL_SECONDS\n    active_budget = BASE_DOCUMENT_WALL_SECONDS\n    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):\n'''
assert old in text, 'download_one header not found'
text=text.replace(old,new,1)
old='''                length = int(r.headers.get("Content-Length") or 0)\n                if length and length > MAX_FILE_BYTES:\n                    raise ValueError(f"declared file size exceeds {MAX_FILE_BYTES} bytes")\n                count = 0\n'''
new='''                length = int(r.headers.get("Content-Length") or 0)\n                if length and length > MAX_FILE_BYTES:\n                    raise ValueError(f"declared file size exceeds {MAX_FILE_BYTES} bytes")\n                active_budget = wall_budget_for_length(length)\n                deadline = max(deadline, started + active_budget)\n                count = 0\n'''
assert old in text, 'content length block not found'
text=text.replace(old,new,1)
old='''                        count += len(chunk)\n                        if count > MAX_FILE_BYTES or total_bytes + count > MAX_TOTAL_BYTES:\n'''
new='''                        count += len(chunk)\n                        if not length:\n                            active_budget = wall_budget_for_length(count)\n                            deadline = max(deadline, started + active_budget)\n                        if count > MAX_FILE_BYTES or total_bytes + count > MAX_TOTAL_BYTES:\n'''
assert old in text, 'download chunk block not found'
text=text.replace(old,new,1)
text=text.replace('''raise TimeoutError(f"document wall-clock budget exceeded ({MAX_DOCUMENT_WALL_SECONDS:.0f}s)")''','''raise TimeoutError(f"document wall-clock budget exceeded ({active_budget:.0f}s)")''')
p.write_text(text,encoding='utf-8')

p=Path('tests/test_corporate_docs_collect.py')
t=p.read_text(encoding='utf-8')
t=t.replace('from corporate_docs_collect import DOWNLOAD_ATTEMPTS, DOWNLOAD_TIMEOUT, PREFLIGHT_TIMEOUT, ATTACHMENT_DISCOVERY_TIMEOUT, MAX_DOCUMENT_WALL_SECONDS, collect','from corporate_docs_collect import DOWNLOAD_ATTEMPTS, DOWNLOAD_TIMEOUT, PREFLIGHT_TIMEOUT, ATTACHMENT_DISCOVERY_TIMEOUT, BASE_DOCUMENT_WALL_SECONDS, MAX_DOCUMENT_WALL_SECONDS, wall_budget_for_length, collect',1)
old_test='''    def test_runtime_budget_is_bounded(self):\n        self.assertLessEqual(DOWNLOAD_ATTEMPTS,2)\n        self.assertLessEqual(PREFLIGHT_TIMEOUT[1],10)\n        self.assertLessEqual(DOWNLOAD_TIMEOUT[1],25)\n        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[0],15)\n        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[1],30)\n        self.assertLessEqual(MAX_DOCUMENT_WALL_SECONDS,120)\n'''
new_test='''    def test_runtime_budget_is_bounded(self):\n        self.assertLessEqual(DOWNLOAD_ATTEMPTS,2)\n        self.assertLessEqual(PREFLIGHT_TIMEOUT[1],15)\n        self.assertLessEqual(DOWNLOAD_TIMEOUT[1],60)\n        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[0],20)\n        self.assertLessEqual(ATTACHMENT_DISCOVERY_TIMEOUT[1],60)\n        self.assertLessEqual(BASE_DOCUMENT_WALL_SECONDS,120)\n        self.assertLessEqual(MAX_DOCUMENT_WALL_SECONDS,360)\n        self.assertGreater(MAX_DOCUMENT_WALL_SECONDS,BASE_DOCUMENT_WALL_SECONDS)\n'''
assert old_test in t, 'runtime budget test block not found'
t=t.replace(old_test,new_test,1)
marker='''    def test_slow_drip_download_hits_total_wall_clock_budget(self):\n'''
case='''    def test_large_declared_file_gets_bounded_size_aware_budget(self):\n        small = wall_budget_for_length(2 * 1024 * 1024)\n        large = wall_budget_for_length(32 * 1024 * 1024)\n        huge = wall_budget_for_length(100 * 1024 * 1024)\n        self.assertEqual(small, BASE_DOCUMENT_WALL_SECONDS)\n        self.assertGreater(large, BASE_DOCUMENT_WALL_SECONDS)\n        self.assertLessEqual(large, MAX_DOCUMENT_WALL_SECONDS)\n        self.assertEqual(huge, MAX_DOCUMENT_WALL_SECONDS)\n\n'''
assert marker in t, 'slow drip marker missing'
t=t.replace(marker,case+marker,1)
# Existing slow-drip fake has a tiny declared length and must still hit the 120s base budget.
p.write_text(t,encoding='utf-8')
