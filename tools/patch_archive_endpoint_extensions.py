from pathlib import Path

PATH = Path('orchestrator/archive_builder.py')
text = PATH.read_text(encoding='utf-8')

old_import = "import csv, hashlib, json, re, shutil, subprocess\n"
new_import = "import csv, hashlib, io, json, re, shutil, subprocess, zipfile\n"
if old_import not in text and new_import not in text:
    raise SystemExit('archive_builder import anchor not found')
text = text.replace(old_import, new_import, 1)

old_constants = "USER_ROOT = \"01_사용자자료\"\nSYSTEM_ROOT = \"90_시스템원본\"\n"
new_constants = "USER_ROOT = \"01_사용자자료\"\nSYSTEM_ROOT = \"90_시스템원본\"\nWEB_ENDPOINT_EXTENSIONS = {'.do', '.jsp', '.action', '.cgi', '.php', '.aspx'}\n"
if old_constants in text:
    text = text.replace(old_constants, new_constants, 1)
elif "WEB_ENDPOINT_EXTENSIONS" not in text:
    raise SystemExit('archive_builder constant anchor not found')

old_func = '''def unique_copy(src,directory,name=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); src=Path(src)
    target=directory/safe(name or src.name)
    if not target.exists(): return copy_file(src,target)
    if sha256(src)==sha256(target): return target
    suffix=target.suffix; stem=target.stem; n=2
    while True:
        candidate=directory/f"{stem}__{n}{suffix}"
        if not candidate.exists(): return copy_file(src,candidate)
        n+=1
'''

new_func = '''def detect_payload_extension(path):
    p=Path(path)
    try:
        with p.open('rb') as f: data=f.read(8192)
    except OSError: return None
    stripped=data.lstrip(); lower=stripped.lower()
    if data.startswith(b'%PDF-'): return '.pdf'
    if data.startswith(b'\\x89PNG\\r\\n\\x1a\\n'): return '.png'
    if data.startswith(b'\\xff\\xd8\\xff'): return '.jpg'
    if data.startswith((b'GIF87a',b'GIF89a')): return '.gif'
    if lower.startswith(b'<!doctype html') or lower.startswith(b'<html') or b'<html' in lower[:2048]: return '.html'
    if data.startswith(b'PK\\x03\\x04'):
        try:
            with zipfile.ZipFile(p,'r') as z:
                names=set(z.namelist())
                if '[Content_Types].xml' in names:
                    if any(x.startswith('xl/') for x in names): return '.xlsx'
                    if any(x.startswith('word/') for x in names): return '.docx'
                    if any(x.startswith('ppt/') for x in names): return '.pptx'
                return '.zip'
        except zipfile.BadZipFile: return None
    return None


def normalize_user_filename(src,name):
    raw=safe(name or Path(src).name); p=Path(raw)
    if p.suffix.lower() not in WEB_ENDPOINT_EXTENSIONS: return raw
    detected=detect_payload_extension(src)
    return safe(p.stem+detected) if detected else raw


def unique_copy(src,directory,name=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); src=Path(src)
    target=directory/normalize_user_filename(src,name)
    if not target.exists(): return copy_file(src,target)
    if sha256(src)==sha256(target): return target
    suffix=target.suffix; stem=target.stem; n=2
    while True:
        candidate=directory/f"{stem}__{n}{suffix}"
        if not candidate.exists(): return copy_file(src,candidate)
        n+=1
'''

if old_func in text:
    text = text.replace(old_func, new_func, 1)
elif 'def normalize_user_filename' not in text:
    raise SystemExit('unique_copy anchor not found')

PATH.write_text(text, encoding='utf-8')
print('patched', PATH)
