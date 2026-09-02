from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .build_application_material_package import build
    from .validate_application_material_package import validate_package
except ImportError:
    from build_application_material_package import build
    from validate_application_material_package import validate_package


MANIFEST_SUFFIX = "/00_자료목록/Archive_Manifest.json"


def _find_unique_manifest(z: zipfile.ZipFile) -> str:
    matches = [
        name
        for name in z.namelist()
        if not name.endswith("/") and name.endswith(MANIFEST_SUFFIX)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one Archive_Manifest.json in Human Archive, found {len(matches)}"
        )
    return matches[0]


def read_archive_manifest(input_zip: str) -> dict:
    with zipfile.ZipFile(input_zip, "r") as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"Human Archive ZIP integrity failure: {bad}")
        manifest_name = _find_unique_manifest(z)
        manifest = json.loads(z.read(manifest_name).decode("utf-8-sig"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Archive_Manifest.json must contain a JSON object")
    return manifest


def assert_verified_human_archive(manifest: dict) -> None:
    completeness = str(manifest.get("archive_completeness") or "")
    if completeness != "COMPLETE":
        raise RuntimeError(
            f"Human Archive is not verified COMPLETE: archive_completeness={completeness!r}"
        )

    blocking = manifest.get("blocking_acceptance_checks")
    if isinstance(blocking, dict):
        failed = sorted(key for key, value in blocking.items() if value is not True)
        if failed:
            raise RuntimeError(
                "Human Archive has failed blocking acceptance checks: " + ", ".join(failed)
            )


def default_package_label(company_display_name: str) -> str:
    text = str(company_display_name or "").strip().replace("㈜", "")
    text = re.sub(r"^\s*\(\s*주\s*\)\s*", "", text)
    text = re.sub(r"\s*\(\s*주\s*\)\s*$", "", text)
    text = re.sub(r"^\s*주식회사\s+", "", text)
    text = re.sub(r"\s+주식회사\s*$", "", text)
    return text.strip() or str(company_display_name or "").strip()


def safe_package_label(value: str) -> str:
    label = str(value or "").strip()
    label = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", label)
    label = re.sub(r"\s+", " ", label).strip(" ._")
    if not label:
        raise RuntimeError("package label is empty after filename sanitization")
    if label in {".", ".."}:
        raise RuntimeError("invalid package label")
    return label


def build_from_human_archive(
    input_zip: str,
    output_dir: str,
    source_run: str,
    package_label: str | None = None,
) -> dict[str, object]:
    manifest = read_archive_manifest(input_zip)
    assert_verified_human_archive(manifest)

    company = str(manifest.get("company_display_name") or "").strip()
    if not company:
        raise RuntimeError("Archive_Manifest.json is missing company_display_name")

    label = safe_package_label(package_label or default_package_label(company))
    output_root = f"{label}_지원용_환경자료"
    output_path = Path(output_dir) / f"{output_root}.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    build_result = build(
        input_zip,
        str(output_path),
        output_root,
        company,
        str(source_run),
    )
    validation = validate_package(str(output_path), company)

    return {
        "schema_version": "application-material-from-archive-1.0",
        "status": "PASS",
        "company": company,
        "company_id": str(manifest.get("company_id") or ""),
        "package_label": label,
        "source_run_id": str(source_run),
        "source_archive_completeness": str(manifest.get("archive_completeness") or ""),
        "source_archive_root": str(manifest.get("archive_root") or ""),
        "output_root": output_root,
        "output_zip": str(output_path),
        "output_zip_sha256": build_result["zip_sha256"],
        "envinfo_disclosure_records": build_result["envinfo_disclosure_records"],
        "envinfo_attachment_references": build_result["envinfo_attachment_references"],
        "envinfo_unique_attachments": build_result["envinfo_unique_attachments"],
        "envinfo_duplicate_attachment_references": build_result[
            "envinfo_duplicate_attachment_references"
        ],
        "envinfo_physical_files": build_result["envinfo_physical_files"],
        "envinfo_site_count": build_result["envinfo_site_count"],
        "validation_checks": validation["checks"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Verified Human_Archive.zip")
    parser.add_argument("--output-dir", default="delivery")
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--package-label", default="")
    parser.add_argument("--summary-out", default="")
    args = parser.parse_args()

    result = build_from_human_archive(
        args.input,
        args.output_dir,
        args.source_run,
        args.package_label or None,
    )
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
