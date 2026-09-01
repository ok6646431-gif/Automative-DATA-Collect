from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path


TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ARTIFACT_PATTERN_RE = re.compile(r"^[A-Za-z0-9*?][A-Za-z0-9._*?-]{0,127}$")
RELEASE_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}\.zip$")


def load_config(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "release-delivery-1.0":
        raise ValueError("schema_version must be release-delivery-1.0")

    run_id = data.get("source_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ValueError("source_run_id must be a positive integer")

    tag = data.get("release_tag")
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        raise ValueError("release_tag contains unsupported characters")

    title = data.get("release_title")
    if not isinstance(title, str) or not title.strip() or len(title) > 128 or "\n" in title:
        raise ValueError("release_title must be a single non-empty line of at most 128 characters")

    pattern = data.get("artifact_pattern")
    if not isinstance(pattern, str) or not ARTIFACT_PATTERN_RE.fullmatch(pattern):
        raise ValueError("artifact_pattern contains unsupported characters")

    assets = data.get("expected_assets")
    if not isinstance(assets, list) or not 1 <= len(assets) <= 20:
        raise ValueError("expected_assets must contain between 1 and 20 filenames")
    normalized_assets: list[dict[str, str]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("every expected asset must map source_name to release_name")
        source_name = asset.get("source_name")
        release_name = asset.get("release_name")
        if (
            not isinstance(source_name, str)
            or Path(source_name).name != source_name
            or not source_name.lower().endswith(".zip")
        ):
            raise ValueError(f"source_name must be a ZIP basename: {source_name!r}")
        if not isinstance(release_name, str) or not RELEASE_ASSET_RE.fullmatch(release_name):
            raise ValueError(f"release_name must be an ASCII ZIP basename: {release_name!r}")
        normalized_assets.append({"source_name": source_name, "release_name": release_name})
    source_names = [item["source_name"] for item in normalized_assets]
    release_names = [item["release_name"] for item in normalized_assets]
    if len(source_names) != len(set(source_names)) or len(release_names) != len(set(release_names)):
        raise ValueError("expected_assets contains duplicate source or release filenames")

    data["expected_assets"] = normalized_assets
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_output(path: Path, key: str, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def prepare(config_path: Path, github_output: Path, notes_out: Path) -> None:
    config = load_config(config_path)
    write_output(github_output, "source_run_id", config["source_run_id"])
    write_output(github_output, "release_tag", config["release_tag"])
    write_output(github_output, "release_title", config["release_title"])
    write_output(github_output, "artifact_pattern", config["artifact_pattern"])

    custom_notes = str(config.get("release_notes", "")).strip()
    assets = "\n".join(
        f"- `{item['release_name']}`"
        for item in config["expected_assets"]
    )
    notes = (
        f"{custom_notes}\n\n" if custom_notes else ""
    ) + (
        "## 다운로드 파일\n\n"
        f"{assets}\n\n"
        f"원본 GitHub Actions run: `{config['source_run_id']}`\n\n"
        "각 ZIP은 검증된 Human Archive에서 사용자용 자료만 재분류한 최종 전달본입니다. "
        "파일 무결성 확인용 `SHA256SUMS.txt`를 함께 제공합니다.\n"
    )
    notes_out.write_text(notes, encoding="utf-8")


def stage(config_path: Path, source_dir: Path, asset_dir: Path) -> None:
    config = load_config(config_path)
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True)

    checksum_rows: list[str] = []
    for item in config["expected_assets"]:
        source_name = item["source_name"]
        release_name = item["release_name"]
        matches = [path for path in source_dir.rglob(source_name) if path.is_file()]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one {source_name!r}, found {len(matches)}")
        source = matches[0]
        with zipfile.ZipFile(source, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"ZIP integrity failure in {source_name}: {bad_member}")
        target = asset_dir / release_name
        shutil.copy2(source, target)
        checksum_rows.append(f"{sha256_file(target)}  {release_name}")

    (asset_dir / "SHA256SUMS.txt").write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")
    print(json.dumps({
        "assets": [
            {"name": path.name, "bytes": path.stat().st_size}
            for path in sorted(asset_dir.iterdir())
        ]
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--config", required=True, type=Path)
    prepare_parser.add_argument("--github-output", required=True, type=Path)
    prepare_parser.add_argument("--notes-out", required=True, type=Path)

    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--config", required=True, type=Path)
    stage_parser.add_argument("--source-dir", required=True, type=Path)
    stage_parser.add_argument("--asset-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.config, args.github_output, args.notes_out)
    else:
        stage(args.config, args.source_dir, args.asset_dir)


if __name__ == "__main__":
    main()
