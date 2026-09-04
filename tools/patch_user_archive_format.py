from pathlib import Path


path = Path("orchestrator/archive_stage.py")
text = path.read_text(encoding="utf-8")

import_anchor = "from archive_builder import build_archive, archive_file_index, write_csv, sha256\n"
import_line = "from user_archive_format import normalize_user_archive\n"
if import_line not in text:
    if import_anchor not in text:
        raise RuntimeError("archive_stage import anchor not found")
    text = text.replace(import_anchor, import_anchor + import_line, 1)

old = "    summary=build_archive(root)\n    summary=classify_archive_summary(root,summary)\n"
new = (
    "    summary=build_archive(root)\n"
    "    normalization=normalize_user_archive(root/'Human_Archive'/summary['archive_root'])\n"
    "    summary['user_files']=normalization['user_files']\n"
    "    summary['user_format_normalization']=normalization\n"
    "    summary=classify_archive_summary(root,summary)\n"
)
if new not in text:
    if old not in text:
        raise RuntimeError("archive_stage build anchor not found")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("patched archive_stage.py")
