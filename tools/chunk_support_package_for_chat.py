from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path

TARGET_BYTES = 75 * 1024 * 1024
MAX_SINGLE_BYTES = 95 * 1024 * 1024
WEB_ENDPOINT_SUFFIXES = {'.do', '.jsp', '.action', '.cgi', '.php', '.aspx'}


def bin_pack(infos: list[zipfile.ZipInfo]) -> list[list[zipfile.ZipInfo]]:
    bins: list[list[zipfile.ZipInfo]] = []
    totals: list[int] = []
    for info in sorted(infos, key=lambda x: x.file_size, reverse=True):
        if info.file_size > MAX_SINGLE_BYTES:
            raise RuntimeError(f'single file exceeds chat-safe limit: {info.filename} = {info.file_size}')
        placed = False
        for i in sorted(range(len(bins)), key=lambda x: totals[x]):
            if totals[i] + info.file_size <= TARGET_BYTES:
                bins[i].append(info)
                totals[i] += info.file_size
                placed = True
                break
        if not placed:
            bins.append([info])
            totals.append(info.file_size)
    return bins


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--prefix', required=True)
    args = ap.parse_args()

    out_root = Path(args.out_dir)
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    with zipfile.ZipFile(args.input, 'r') as src:
        infos = [i for i in src.infolist() if not i.is_dir()]
        bad_endpoint = [i.filename for i in infos if Path(i.filename).suffix.lower() in WEB_ENDPOINT_SUFFIXES]
        if bad_endpoint:
            raise RuntimeError('web endpoint filenames remain in user package: ' + '; '.join(bad_endpoint[:20]))

        bins = bin_pack(infos)
        manifest = []
        for idx, members in enumerate(bins, start=1):
            part = out_root / f'{args.prefix}_{idx:02d}'
            part.mkdir(parents=True)
            raw_total = 0
            for info in members:
                target = part / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with src.open(info, 'r') as r, target.open('wb') as w:
                    shutil.copyfileobj(r, w, length=8 * 1024 * 1024)
                raw_total += info.file_size
            note = part / '분할안내.txt'
            note.write_text(
                f'{args.prefix} ChatGPT 전달용 분할 {idx}/{len(bins)}\n'
                '각 artifact는 ChatGPT 파일 전달 제한을 맞추기 위해 분할되었습니다.\n'
                '모든 part를 받으면 원래 지원용 자료 전체가 됩니다. 폴더 상대경로는 원본과 동일합니다.\n',
                encoding='utf-8',
            )
            manifest.append({'part': part.name, 'files': len(members), 'raw_bytes': raw_total})

    (out_root / 'chunk_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'input': args.input, 'parts': len(manifest), 'manifest': manifest}, ensure_ascii=False))


if __name__ == '__main__':
    main()
