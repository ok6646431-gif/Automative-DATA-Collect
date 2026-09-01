from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile


MAX_DELIVERY_BYTES = 500 * 1024 * 1024


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_members(src: zipfile.ZipFile, names: list[str], output: str, extras: dict[str, bytes] | None = None) -> dict[str, object]:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        for name in names:
            info = src.getinfo(name)
            out.writestr(name, src.read(info))
        for name, data in (extras or {}).items():
            out.writestr(name, data)
    with zipfile.ZipFile(output, "r") as check:
        bad = check.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure in {output}: {bad}")
        count = len([n for n in check.namelist() if not n.endswith("/")])
    size = os.path.getsize(output)
    if size > MAX_DELIVERY_BYTES:
        raise RuntimeError(f"Delivery part exceeds 500 MiB: {output} = {size}")
    return {"path": output, "bytes": size, "files": count, "sha256": sha256_file(output)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--prefix", required=True)
    args = p.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    with zipfile.ZipFile(args.input, "r") as src:
        infos = [i for i in src.infolist() if not i.is_dir()]
        env_infos = [i for i in infos if "/02_환경인허가_ENVINFO/" in i.filename]
        core_infos = [i for i in infos if "/02_환경인허가_ENVINFO/" not in i.filename]
        metadata_infos = [
            i for i in core_infos
            if "/00_자료목록/" in i.filename or i.filename.endswith("/README_먼저보기.txt")
        ]

        bins: list[list[zipfile.ZipInfo]] = [[], []]
        totals = [0, 0]
        for info in sorted(env_infos, key=lambda x: x.compress_size, reverse=True):
            idx = 0 if totals[0] <= totals[1] else 1
            bins[idx].append(info)
            totals[idx] += info.compress_size

        core_path = os.path.join(args.out_dir, f"{args.prefix}_핵심자료.zip")
        env1_path = os.path.join(args.out_dir, f"{args.prefix}_ENVINFO_자료_1.zip")
        env2_path = os.path.join(args.out_dir, f"{args.prefix}_ENVINFO_자료_2.zip")

        root = infos[0].filename.split("/", 1)[0] if infos else args.prefix
        common_note = (
            "이 파일은 512MB 전달 한도를 맞추기 위해 지원용 환경자료를 분할한 것입니다.\n"
            "핵심자료 ZIP에는 ENV-INFO 대용량 자료를 제외한 회사보고서·정책·TMS·PRTR·화학물질통계·검토자료가 들어 있습니다.\n"
            "ENVINFO_자료_1/2는 02_환경인허가_ENVINFO 폴더를 용량 기준으로 나눈 것이며, 두 파일을 모두 보관하면 전체 ENV-INFO 자료가 됩니다.\n"
        ).encode("utf-8")

        results = []
        results.append(copy_members(src, [i.filename for i in core_infos], core_path))
        for idx, (bin_infos, path) in enumerate(zip(bins, [env1_path, env2_path]), start=1):
            names = [i.filename for i in metadata_infos] + [i.filename for i in bin_infos]
            extras = {f"{root}/분할안내_ENVINFO_{idx}.txt": common_note}
            results.append(copy_members(src, names, path, extras=extras))

    summary = {
        "source": args.input,
        "envinfo_files": len(env_infos),
        "core_files": len(core_infos),
        "envinfo_bin_estimated_compressed_bytes": totals,
        "parts": results,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
