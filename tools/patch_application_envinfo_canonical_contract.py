from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Human Archive: retain a machine-readable companion to the user-facing XLSX
# so downstream packages can reconstruct original site/year attachment relations.
path = "orchestrator/archive_user_dedup_v2.py"
replace_once(path, "import hashlib\nimport json\n", "import csv\nimport hashlib\nimport json\n")
replace_once(
    path,
    'REFERENCE_XLSX = "ENVINFO_첨부자료_참조표.xlsx"\n',
    'REFERENCE_XLSX = "ENVINFO_첨부자료_참조표.xlsx"\nREFERENCE_CSV = "ENVINFO_첨부자료_참조표.csv"\n',
)
replace_once(
    path,
    "    wb.close()\n\n\ndef _remove_empty_dirs(root: Path) -> None:\n",
    '''    wb.close()\n\n\ndef _write_reference_csv(path: Path, rows: list[dict]) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    fields = [\"사업장\", \"공개연도\", \"원래_사용자경로\", \"최종_보존경로\", \"파일명\", \"용량_bytes\", \"SHA256\", \"처리\"]\n    with path.open(\"w\", encoding=\"utf-8-sig\", newline=\"\") as f:\n        writer = csv.DictWriter(f, fieldnames=fields, extrasaction=\"ignore\")\n        writer.writeheader()\n        writer.writerows(rows)\n\n\ndef _remove_empty_dirs(root: Path) -> None:\n''',
)
replace_once(
    path,
    '''    ref_path = archive_root / "00_자료목록" / REFERENCE_XLSX\n    if refs:\n        _write_reference_xlsx(ref_path, refs)\n\n    readme = archive_root / "00_자료목록" / "README_먼저읽기.txt"\n''',
    '''    ref_path = archive_root / "00_자료목록" / REFERENCE_XLSX\n    ref_csv_path = archive_root / "00_자료목록" / REFERENCE_CSV\n    if refs:\n        _write_reference_xlsx(ref_path, refs)\n        _write_reference_csv(ref_csv_path, refs)\n\n    readme = archive_root / "00_자료목록" / "README_먼저읽기.txt"\n''',
)
replace_once(
    path,
    '''        "envinfo_attachment_reference_file": str(ref_path.relative_to(archive_root)) if refs else "",\n    }\n''',
    '''        "envinfo_attachment_reference_file": str(ref_path.relative_to(archive_root)) if refs else "",\n        "envinfo_attachment_reference_csv": str(ref_csv_path.relative_to(archive_root)) if refs else "",\n    }\n''',
)
replace_once(
    path,
    '''            "envinfo_attachment_reference_file": "",\n        }\n''',
    '''            "envinfo_attachment_reference_file": "",\n            "envinfo_attachment_reference_csv": "",\n        }\n''',
)


# 2) Application builder: understand the Human Archive canonical attachment store and
# restore logical site/year relations from the CSV instead of treating the store as a site.
path = "tools/build_application_material_package.py"
replace_once(
    path,
    'ENVINFO_ATTACHMENT_MARKER = "/첨부자료/"\n',
    'ENVINFO_ATTACHMENT_MARKER = "/첨부자료/"\nENVINFO_CENTRAL_FOLDER = "첨부자료_원문"\nHUMAN_ENVINFO_REFERENCE_CSV = "ENVINFO_첨부자료_참조표.csv"\n',
)
replace_once(
    path,
    '''def is_envinfo_attachment(path: str) -> bool:\n    return path.startswith(ENVINFO_PREFIX) and ENVINFO_ATTACHMENT_MARKER in path\n\n\ndef envinfo_site(path: str) -> str:\n    parts = PurePosixPath(path).parts\n    return parts[1] if len(parts) > 1 and parts[0] == ENVINFO_PREFIX.rstrip("/") else ""\n''',
    '''def is_envinfo_canonical_attachment(path: str) -> bool:\n    parts = PurePosixPath(path).parts\n    return (\n        len(parts) > 2\n        and parts[0] == ENVINFO_PREFIX.rstrip("/")\n        and parts[1] == ENVINFO_CENTRAL_FOLDER\n    )\n\n\ndef is_envinfo_attachment(path: str) -> bool:\n    return (\n        path.startswith(ENVINFO_PREFIX)\n        and (ENVINFO_ATTACHMENT_MARKER in path or is_envinfo_canonical_attachment(path))\n    )\n\n\ndef envinfo_site(path: str) -> str:\n    parts = PurePosixPath(path).parts\n    if len(parts) <= 1 or parts[0] != ENVINFO_PREFIX.rstrip("/"):\n        return ""\n    if parts[1] == ENVINFO_CENTRAL_FOLDER:\n        return ""\n    return parts[1]\n''',
)
replace_once(
    path,
    '''    return result\n\n\ndef build(input_zip: str, output_zip: str, root_name: str, company: str, source_run: str) -> dict[str, object]:\n''',
    '''    return result\n\n\ndef read_human_envinfo_attachment_references(src: zipfile.ZipFile) -> list[dict[str, str]]:\n    \"\"\"Read canonical ENVINFO relations emitted by Human Archive user dedup.\n\n    Only original site-level ENVINFO attachment occurrences are returned. Generated\n    sustainability/policy copies are provenance redirects, not additional source\n    attachment relations.\n    \"\"\"\n    suffix = f\"/00_자료목록/{HUMAN_ENVINFO_REFERENCE_CSV}\"\n    matches = [info for info in src.infolist() if not info.is_dir() and info.filename.endswith(suffix)]\n    if not matches:\n        return []\n    if len(matches) != 1:\n        raise RuntimeError(f\"expected exactly one {HUMAN_ENVINFO_REFERENCE_CSV}, found {len(matches)}\")\n    text = src.read(matches[0]).decode(\"utf-8-sig\")\n    rows = list(csv.DictReader(io.StringIO(text)))\n    result = []\n    prefix = \"01_사용자자료/03_환경정보공개시스템/\"\n    for row in rows:\n        original = str(row.get(\"원래_사용자경로\") or \"\")\n        if not original.startswith(prefix) or \"/첨부자료/\" not in original:\n            continue\n        result.append({key: str(value or \"\") for key, value in row.items()})\n    return result\n\n\ndef build(input_zip: str, output_zip: str, root_name: str, company: str, source_run: str) -> dict[str, object]:\n''',
)
replace_once(
    path,
    '''    envinfo_source_duplicate_attachment_references = 0\n    envinfo_logical_paths: set[str] = set()\n\n    with zipfile.ZipFile(input_zip, "r") as src, zipfile.ZipFile(\n''',
    '''    envinfo_source_duplicate_attachment_references = 0\n    envinfo_logical_paths: set[str] = set()\n    source_relative_to_final: dict[str, str] = {}\n    final_path_bytes: dict[str, int] = {}\n\n    with zipfile.ZipFile(input_zip, "r") as src, zipfile.ZipFile(\n''',
)
replace_once(
    path,
    '''    ) as out:\n        prior_envinfo_references = read_prior_envinfo_attachment_references(src)\n        for info in src.infolist():\n''',
    '''    ) as out:\n        prior_envinfo_references = read_prior_envinfo_attachment_references(src)\n        human_envinfo_references = read_human_envinfo_attachment_references(src)\n        for info in src.infolist():\n''',
)
replace_once(
    path,
    '''            retained_path = ""\n            attachment = is_envinfo_attachment(final_rel)\n''',
    '''            retained_path = ""\n            attachment = is_envinfo_attachment(final_rel)\n            canonical_attachment = is_envinfo_canonical_attachment(final_rel)\n''',
)
replace_once(
    path,
    '''            if action == "SKIPPED_IDENTICAL_PATH_COLLISION":\n                skipped += 1\n                continue\n            taken[final_rel] = digest\n\n            if attachment:\n                site = envinfo_site(final_rel)\n                year = path_year(final_rel)\n                stats = envinfo_site_stats[site]\n                stats["attachment_references"] = int(stats["attachment_references"]) + 1\n                stats["attachment_hashes"].add(digest)\n                if year:\n                    stats["years"].add(year)\n                duplicate_reference = bool(retained_path)\n                envinfo_attachment_references.append(\n                    {\n                        "logical_path": final_rel,\n                        "stored_path": retained_path or final_rel,\n                        "site": site,\n                        "year": year,\n                        "bytes": len(data),\n                        "sha256": digest,\n                        "reference_type": (\n                            "IDENTICAL_SHA256_REFERENCE" if duplicate_reference else "STORED_FILE"\n                        ),\n                        "source_archive_path": info.filename,\n                    }\n                )\n                envinfo_logical_paths.add(final_rel)\n                if duplicate_reference:\n                    envinfo_duplicate_attachment_references += 1\n                    envinfo_duplicate_attachment_bytes_avoided += len(data)\n                    continue\n                envinfo_attachment_by_sha[digest] = final_rel\n                envinfo_unique_attachment_bytes += len(data)\n''',
    '''            if action == "SKIPPED_IDENTICAL_PATH_COLLISION":\n                skipped += 1\n                source_relative_to_final[relative] = final_rel\n                continue\n            taken[final_rel] = digest\n            source_relative_to_final[relative] = retained_path or final_rel\n            if not retained_path:\n                final_path_bytes[final_rel] = len(data)\n\n            if attachment:\n                site = envinfo_site(final_rel)\n                year = path_year(final_rel)\n                duplicate_reference = bool(retained_path)\n                if not canonical_attachment:\n                    stats = envinfo_site_stats[site]\n                    stats["attachment_references"] = int(stats["attachment_references"]) + 1\n                    stats["attachment_hashes"].add(digest)\n                    if year:\n                        stats["years"].add(year)\n                    envinfo_attachment_references.append(\n                        {\n                            "logical_path": final_rel,\n                            "stored_path": retained_path or final_rel,\n                            "site": site,\n                            "year": year,\n                            "bytes": len(data),\n                            "sha256": digest,\n                            "reference_type": (\n                                "IDENTICAL_SHA256_REFERENCE" if duplicate_reference else "STORED_FILE"\n                            ),\n                            "source_archive_path": info.filename,\n                        }\n                    )\n                    envinfo_logical_paths.add(final_rel)\n                if duplicate_reference:\n                    envinfo_duplicate_attachment_references += 1\n                    envinfo_duplicate_attachment_bytes_avoided += len(data)\n                    continue\n                envinfo_attachment_by_sha[digest] = final_rel\n                envinfo_unique_attachment_bytes += len(data)\n''',
)
replace_once(
    path,
    '''        envinfo_source_attachment_paths = len(envinfo_attachment_references)\n        for prior in prior_envinfo_references:\n''',
    '''        # Human Archive canonicalization moves site attachments to a shared SHA\n        # store and may redirect exact copies to a canonical report/policy file. Restore\n        # the original site/year relationships without creating duplicate bytes.\n        for ref in human_envinfo_references:\n            original = str(ref.get("원래_사용자경로") or "")\n            retained_source = str(ref.get("최종_보존경로") or "")\n            logical_path = map_relative_path(original)\n            if not logical_path or logical_path in envinfo_logical_paths:\n                continue\n            stored_path = source_relative_to_final.get(retained_source, "")\n            if not stored_path:\n                mapped_retained = map_relative_path(retained_source)\n                if mapped_retained and mapped_retained in taken:\n                    stored_path = mapped_retained\n            digest = str(ref.get("SHA256") or "")\n            if not stored_path or stored_path not in taken:\n                raise RuntimeError(\n                    "Human Archive ENVINFO reference points to a file not copied into support package: "\n                    f"{retained_source}"\n                )\n            if not digest or taken[stored_path] != digest:\n                raise RuntimeError(\n                    "Human Archive ENVINFO reference digest mismatch: "\n                    f"stored={stored_path} expected={digest} actual={taken.get(stored_path)}"\n                )\n            if digest not in envinfo_attachment_by_sha:\n                envinfo_attachment_by_sha[digest] = stored_path\n                envinfo_unique_attachment_bytes += final_path_bytes.get(stored_path, 0)\n            site = envinfo_site(logical_path)\n            year = str(ref.get("공개연도") or path_year(logical_path))\n            stats = envinfo_site_stats[site]\n            stats["attachment_references"] = int(stats["attachment_references"]) + 1\n            stats["attachment_hashes"].add(digest)\n            if year:\n                stats["years"].add(year)\n            byte_count = int(str(ref.get("용량_bytes") or "0") or 0)\n            envinfo_attachment_references.append(\n                {\n                    "logical_path": logical_path,\n                    "stored_path": stored_path,\n                    "site": site,\n                    "year": year,\n                    "bytes": byte_count,\n                    "sha256": digest,\n                    "reference_type": "HUMAN_ARCHIVE_CANONICAL_REFERENCE",\n                    "source_archive_path": original,\n                }\n            )\n            envinfo_logical_paths.add(logical_path)\n\n        for prior in prior_envinfo_references:\n''',
)
replace_once(
    path,
    '''        envinfo_attachment_references.sort(key=lambda row: str(row["logical_path"]))\n        envinfo_attachment_count = len(envinfo_attachment_references)\n        envinfo_unique_attachment_count = len(envinfo_attachment_by_sha)\n        envinfo_physical_files = envinfo_record_documents + envinfo_unique_attachment_count\n        envinfo_physical_bytes = envinfo_record_bytes + envinfo_unique_attachment_bytes\n        envinfo_site_count = len([site for site in envinfo_site_stats if site])\n''',
    '''        envinfo_attachment_references.sort(key=lambda row: str(row["logical_path"]))\n        envinfo_attachment_count = len(envinfo_attachment_references)\n        referenced_digests = {str(row.get("sha256") or "") for row in envinfo_attachment_references if str(row.get("sha256") or "")}\n        envinfo_unique_attachment_count = len(referenced_digests)\n        envinfo_unique_attachment_bytes = sum(\n            final_path_bytes.get(envinfo_attachment_by_sha.get(digest, ""), 0)\n            for digest in referenced_digests\n        )\n        envinfo_duplicate_attachment_references = max(0, envinfo_attachment_count - envinfo_unique_attachment_count)\n        envinfo_source_attachment_paths = max(0, envinfo_attachment_count - envinfo_source_duplicate_attachment_references)\n        relation_bytes = sum(int(row.get("bytes") or 0) for row in envinfo_attachment_references)\n        envinfo_duplicate_attachment_bytes_avoided = max(0, relation_bytes - envinfo_unique_attachment_bytes)\n        envinfo_physical_files = envinfo_record_documents + envinfo_unique_attachment_count\n        envinfo_physical_bytes = envinfo_record_bytes + envinfo_unique_attachment_bytes\n        envinfo_site_count = len([site for site in envinfo_site_stats if site])\n''',
)
replace_once(
    path,
    '''        envinfo_physical_members = [name for name in names if f"/{ENVINFO_PREFIX}" in name]\n        if len(envinfo_physical_members) != summary["envinfo_physical_files"]:\n            raise RuntimeError(\n                "ENVINFO physical-file count mismatch: "\n                f"archive={len(envinfo_physical_members)} summary={summary['envinfo_physical_files']}"\n            )\n''',
    '''        relative_names = [name[len(root_name) + 1:] for name in names if name.startswith(root_name + "/") and not name.endswith("/")]\n        record_members = [\n            rel for rel in relative_names\n            if rel.startswith(ENVINFO_PREFIX) and not is_envinfo_attachment(rel)\n        ]\n        stored_paths = {str(row.get("stored_path") or "") for row in envinfo_attachment_references if str(row.get("stored_path") or "")}\n        missing_stored = sorted(path for path in stored_paths if f"{root_name}/{path}" not in names)\n        if missing_stored:\n            raise RuntimeError(f"ENVINFO stored attachment paths missing from support package: {missing_stored[:5]}")\n        if len(record_members) + len(stored_paths) != summary["envinfo_physical_files"]:\n            raise RuntimeError(\n                "ENVINFO physical-file count mismatch: "\n                f"records={len(record_members)} stored_attachments={len(stored_paths)} "\n                f"summary={summary['envinfo_physical_files']}"\n            )\n''',
)


# 3) Validator: classify the shared store as attachment storage, and validate reference
# stored paths wherever Human Archive canonicalization placed the bytes.
path = "tools/validate_application_material_package.py"
replace_once(
    path,
    'ENVINFO_PREFIX = "02_환경인허가_ENVINFO/"\n',
    'ENVINFO_PREFIX = "02_환경인허가_ENVINFO/"\nENVINFO_CENTRAL_FOLDER = "첨부자료_원문"\n',
)
replace_once(
    path,
    '''def _site_matches_target(site: str, targets: Iterable[str]) -> bool:\n''',
    '''def _is_envinfo_attachment_storage(path: str) -> bool:\n    parts = PurePosixPath(path).parts\n    return (\n        path.startswith(ENVINFO_PREFIX)\n        and (\n            "/첨부자료/" in path\n            or (len(parts) > 2 and parts[0] == ENVINFO_PREFIX.rstrip("/") and parts[1] == ENVINFO_CENTRAL_FOLDER)\n        )\n    )\n\n\ndef _site_matches_target(site: str, targets: Iterable[str]) -> bool:\n''',
)
old_block = '''        envinfo_members = [p for p in relative_names if p.startswith(ENVINFO_PREFIX)]\n        if len(envinfo_members) != physical:\n            raise RuntimeError(\n                f"ENVINFO physical member mismatch: archive={len(envinfo_members)} summary={physical}"\n            )\n        attachment_members = [p for p in envinfo_members if "/첨부자료/" in p]\n        record_members = [p for p in envinfo_members if "/첨부자료/" not in p]\n        if len(attachment_members) != unique_attachments or len(record_members) != disclosure:\n            raise RuntimeError(\n                "ENVINFO member classes disagree with summary: "\n                f"records={len(record_members)}/{disclosure}, attachments={len(attachment_members)}/{unique_attachments}"\n            )\n\n        attachment_hashes: dict[str, str] = {}\n        physical_sha_to_path: dict[str, str] = {}\n        for rel in attachment_members:\n            data = z.read(f"{root}/{rel}")\n            digest = sha256_bytes(data)\n            if digest in physical_sha_to_path:\n                raise RuntimeError(\n                    "duplicate ENVINFO physical attachment bytes remain: "\n                    f"{physical_sha_to_path[digest]} and {rel}"\n                )\n            physical_sha_to_path[digest] = rel\n            attachment_hashes[rel] = digest\n        checks.append("ENVINFO_PHYSICAL_SHA_UNIQUE")\n\n        ref_rows = _read_csv(z, "/00_자료목록/ENVINFO_첨부자료_참조목록.csv")\n        if len(ref_rows) != references:\n            raise RuntimeError(\n                f"ENVINFO reference row mismatch: csv={len(ref_rows)} summary={references}"\n            )\n        logical_seen: set[str] = set()\n        for row in ref_rows:\n            logical = row.get("logical_path", "")\n            stored = row.get("stored_path", "")\n            digest = row.get("sha256", "")\n            if not logical or logical in logical_seen:\n                raise RuntimeError(f"duplicate or empty ENVINFO logical path: {logical!r}")\n            logical_seen.add(logical)\n            if stored not in attachment_hashes:\n                raise RuntimeError(f"ENVINFO reference points to missing attachment: {stored}")\n            if attachment_hashes[stored] != digest:\n                raise RuntimeError(\n                    f"ENVINFO reference digest mismatch: stored={stored} csv={digest} actual={attachment_hashes[stored]}"\n                )\n        checks.append("ENVINFO_REFERENCE_INTEGRITY")\n\n        sites = sorted({PurePosixPath(p).parts[1] for p in envinfo_members if len(PurePosixPath(p).parts) > 1})\n        if len(sites) != site_count:\n            raise RuntimeError(f"ENVINFO site count mismatch: archive={len(sites)} summary={site_count}")\n\n        target_ids = scope.get("target_source_ids") or {}\n        envinfo_target_ids = [str(x) for x in target_ids.get("ENVINFO") or [] if str(x)]\n        if envinfo_target_ids:\n            authorized_names = _authorized_envinfo_site_names(z, scope)\n            outside = [site for site in sites if not _site_matches_target(site, authorized_names)]\n            if outside:\n                raise RuntimeError(\n                    "ENVINFO site outside requested source-ID scope: "\n                    f"outside={outside} authorized_source_names={authorized_names} "\n                    f"target_source_ids={envinfo_target_ids}"\n                )\n        else:\n            target_site_tokens = [\n                str(x) for x in archive_manifest.get("target_site_tokens") or [] if str(x)\n            ]\n            if target_site_tokens:\n                outside = [site for site in sites if not _site_matches_target(site, target_site_tokens)]\n                if outside:\n                    raise RuntimeError(\n                        "ENVINFO site outside requested target_site_tokens: "\n                        f"outside={outside} targets={target_site_tokens}"\n                    )\n        checks.append("ENVINFO_SITE_SCOPE")\n'''
new_block = '''        envinfo_members = [p for p in relative_names if p.startswith(ENVINFO_PREFIX)]\n        attachment_storage_members = [p for p in envinfo_members if _is_envinfo_attachment_storage(p)]\n        record_members = [p for p in envinfo_members if not _is_envinfo_attachment_storage(p)]\n        if len(record_members) != disclosure:\n            raise RuntimeError(\n                "ENVINFO disclosure member count disagrees with summary: "\n                f"records={len(record_members)}/{disclosure}"\n            )\n\n        ref_rows = _read_csv(z, "/00_자료목록/ENVINFO_첨부자료_참조목록.csv")\n        if len(ref_rows) != references:\n            raise RuntimeError(\n                f"ENVINFO reference row mismatch: csv={len(ref_rows)} summary={references}"\n            )\n        relative_name_set = set(relative_names)\n        logical_seen: set[str] = set()\n        attachment_hashes: dict[str, str] = {}\n        physical_sha_to_path: dict[str, str] = {}\n        sites_from_refs: set[str] = set()\n        for row in ref_rows:\n            logical = row.get("logical_path", "")\n            stored = row.get("stored_path", "")\n            digest = row.get("sha256", "")\n            site = str(row.get("site") or "")\n            if site:\n                sites_from_refs.add(site)\n            if not logical or logical in logical_seen:\n                raise RuntimeError(f"duplicate or empty ENVINFO logical path: {logical!r}")\n            logical_seen.add(logical)\n            if not stored or stored not in relative_name_set:\n                raise RuntimeError(f"ENVINFO reference points to missing attachment: {stored}")\n            if stored not in attachment_hashes:\n                actual = sha256_bytes(z.read(f"{root}/{stored}"))\n                if actual in physical_sha_to_path and physical_sha_to_path[actual] != stored:\n                    raise RuntimeError(\n                        "duplicate ENVINFO referenced physical attachment bytes remain: "\n                        f"{physical_sha_to_path[actual]} and {stored}"\n                    )\n                physical_sha_to_path[actual] = stored\n                attachment_hashes[stored] = actual\n            if attachment_hashes[stored] != digest:\n                raise RuntimeError(\n                    f"ENVINFO reference digest mismatch: stored={stored} csv={digest} actual={attachment_hashes[stored]}"\n                )\n        if len(physical_sha_to_path) != unique_attachments:\n            raise RuntimeError(\n                "ENVINFO unique attachment count disagrees with references: "\n                f"referenced_unique={len(physical_sha_to_path)} summary={unique_attachments}"\n            )\n        unreferenced_storage = sorted(set(attachment_storage_members) - set(attachment_hashes))\n        if unreferenced_storage:\n            raise RuntimeError(f"unreferenced ENVINFO attachment storage remains: {unreferenced_storage[:5]}")\n        if len(record_members) + len(physical_sha_to_path) != physical:\n            raise RuntimeError(\n                "ENVINFO physical-file identity failed after canonical references: "\n                f"records={len(record_members)} unique_attachments={len(physical_sha_to_path)} summary={physical}"\n            )\n        checks.append("ENVINFO_PHYSICAL_SHA_UNIQUE")\n        checks.append("ENVINFO_REFERENCE_INTEGRITY")\n\n        record_sites = {\n            PurePosixPath(p).parts[1]\n            for p in record_members\n            if len(PurePosixPath(p).parts) > 1\n        }\n        sites = sorted(record_sites | sites_from_refs)\n        if len(sites) != site_count:\n            raise RuntimeError(f"ENVINFO site count mismatch: archive={len(sites)} summary={site_count}")\n\n        target_ids = scope.get("target_source_ids") or {}\n        envinfo_target_ids = [str(x) for x in target_ids.get("ENVINFO") or [] if str(x)]\n        if envinfo_target_ids:\n            authorized_names = _authorized_envinfo_site_names(z, scope)\n            outside = [site for site in sites if not _site_matches_target(site, authorized_names)]\n            if outside:\n                raise RuntimeError(\n                    "ENVINFO site outside requested source-ID scope: "\n                    f"outside={outside} authorized_source_names={authorized_names} "\n                    f"target_source_ids={envinfo_target_ids}"\n                )\n        else:\n            target_site_tokens = [\n                str(x) for x in archive_manifest.get("target_site_tokens") or [] if str(x)\n            ]\n            if target_site_tokens:\n                outside = [site for site in sites if not _site_matches_target(site, target_site_tokens)]\n                if outside:\n                    raise RuntimeError(\n                        "ENVINFO site outside requested target_site_tokens: "\n                        f"outside={outside} targets={target_site_tokens}"\n                    )\n        checks.append("ENVINFO_SITE_SCOPE")\n'''
replace_once(path, old_block, new_block)


# 4) End-to-end regression for canonical store + cross-folder redirect.
test_path = Path("tests/test_application_envinfo_canonical_contract.py")
if not test_path.exists():
    test_path.write_text(r'''import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from orchestrator.archive_user_dedup_v2 import canonicalize_user_envinfo
from tools.build_application_material_package import build
from tools.validate_application_material_package import validate_package


class ApplicationEnvinfoCanonicalContractTests(unittest.TestCase):
    def test_canonical_store_restores_site_relations_and_crossfolder_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "테스트기업_환경자료"
            env = root / "01_사용자자료" / "03_환경정보공개시스템"
            report = root / "01_사용자자료" / "04_지속가능경영보고서"
            idx = root / "00_자료목록"
            for path in [env / "A사업장" / "첨부자료", env / "B사업장" / "첨부자료", report, idx]:
                path.mkdir(parents=True, exist_ok=True)
            (idx / "README_먼저읽기.txt").write_text("Archive v2 사용 안내\n", encoding="utf-8")

            (env / "A사업장" / "환경정보공개_A사업장_2024.pdf").write_bytes(b"%PDF-detail-a")
            (env / "B사업장" / "환경정보공개_B사업장_2024.pdf").write_bytes(b"%PDF-detail-b")
            shared = b"%PDF-shared" + b"A" * 2000 + b"%%EOF"
            unique = b"%PDF-unique" + b"B" * 1500 + b"%%EOF"
            (env / "A사업장" / "첨부자료" / "2024_공통보고서.pdf").write_bytes(shared)
            (env / "B사업장" / "첨부자료" / "2024_공통보고서.pdf").write_bytes(shared)
            (env / "A사업장" / "첨부자료" / "2024_고유자료.pdf").write_bytes(unique)
            (report / "테스트기업_지속가능경영보고서_2024.pdf").write_bytes(shared)

            stats = canonicalize_user_envinfo(root)
            self.assertEqual(stats["envinfo_attachment_occurrences"], 3)
            self.assertTrue((idx / "ENVINFO_첨부자료_참조표.csv").exists())
            refs = list(csv.DictReader((idx / "ENVINFO_첨부자료_참조표.csv").open(encoding="utf-8-sig", newline="")))
            original_refs = [r for r in refs if "/첨부자료/" in r["원래_사용자경로"]]
            self.assertEqual(len(original_refs), 3)
            self.assertTrue(any("04_지속가능경영보고서" in r["최종_보존경로"] for r in original_refs))

            scope = {
                "schema_version": "1.1",
                "target_source_ids": {"ENVINFO": ["A-ID", "B-ID"]},
                "excluded_source_ids": [],
            }
            manifest = {
                "schema_version": "2.0",
                "company_display_name": "테스트기업",
                "archive_completeness": "COMPLETE",
                "target_site_tokens": ["A사업장", "B사업장"],
                "target_source_ids": {"ENVINFO": ["A-ID", "B-ID"]},
            }
            (idx / "Requested_Scope.json").write_text(json.dumps(scope, ensure_ascii=False), encoding="utf-8")
            (idx / "Archive_Manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            analysis = io.StringIO(newline="")
            writer = csv.DictWriter(analysis, fieldnames=["scope_label", "source_key", "source_site_id", "source_site_name_raw"])
            writer.writeheader()
            writer.writerow({"scope_label": "test", "source_key": "ENVINFO", "source_site_id": "A-ID", "source_site_name_raw": "A사업장"})
            writer.writerow({"scope_label": "test", "source_key": "ENVINFO", "source_site_id": "B-ID", "source_site_name_raw": "B사업장"})
            (idx / "Analysis_Scope.csv").write_text(analysis.getvalue(), encoding="utf-8-sig")

            source = base / "Human_Archive.zip"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for p in root.rglob("*"):
                    if p.is_file():
                        z.write(p, f"{root.name}/{p.relative_to(root).as_posix()}")

            output = base / "support.zip"
            result = build(str(source), str(output), "테스트기업_지원용_환경자료", "테스트기업", "123")
            self.assertEqual(result["envinfo_disclosure_records"], 2)
            self.assertEqual(result["envinfo_attachment_references"], 3)
            self.assertEqual(result["envinfo_unique_attachments"], 2)
            self.assertEqual(result["envinfo_physical_files"], 4)
            self.assertEqual(result["envinfo_site_count"], 2)

            validation = validate_package(str(output), "테스트기업")
            self.assertEqual(validation["status"], "PASS")
            self.assertIn("ENVINFO_SITE_SCOPE", validation["checks"])

            with zipfile.ZipFile(output) as z:
                names = z.namelist()
                self.assertFalse(any("02_환경인허가_ENVINFO/첨부자료_원문/" in n and "환경정보공개_" in n for n in names))
                ref_text = z.read("테스트기업_지원용_환경자료/00_자료목록/ENVINFO_첨부자료_참조목록.csv").decode("utf-8-sig")
                support_refs = list(csv.DictReader(io.StringIO(ref_text)))
                self.assertEqual({r["site"] for r in support_refs}, {"A사업장", "B사업장"})


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("application ENVINFO canonical attachment contract patch applied")
