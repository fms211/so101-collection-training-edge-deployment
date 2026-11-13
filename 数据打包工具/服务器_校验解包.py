#!/usr/bin/env python3
"""Verify a local SO-101 bundle and unpack to a fresh server-side directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tarfile
import tempfile


BLOCK = 1024 * 1024
SAFE_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]*$')
SAFE_REPO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def unpack(archive, parent):
    archive = archive.resolve(strict=True)
    require(archive.is_file(), '数据包不是普通文件。')
    checksum = Path(str(archive) + '.sha256')
    require(checksum.is_file(), f'缺少配套校验文件：{checksum}')
    line = checksum.read_text(encoding='ascii').strip()
    parts = line.split('  ', 1)
    require(len(parts) == 2 and re.fullmatch(r'[0-9a-f]{64}', parts[0]) and parts[1] == archive.name,
            '校验文件格式或数据包文件名不匹配。')
    print('正在校验数据包 SHA-256……', flush=True)
    require(sha_file(archive) == parts[0], '数据包校验失败，请重新复制，不要解包训练。')
    require(parent.is_dir(), f'导入根目录不存在：{parent}')
    with tarfile.open(archive, 'r:') as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        require(len(names) == len(set(names)) and 'BUNDLE_MANIFEST.json' in names and
                'README_解包与训练.txt' in names, '归档文件列表不完整或存在重名。')
        for member in members:
            path = PurePosixPath(member.name)
            require(member.isfile() and not path.is_absolute() and '..' not in path.parts and
                    '\\' not in member.name and member.name == str(path), f'归档包含不安全的路径：{member.name}')
        manifest = json.load(tar.extractfile('BUNDLE_MANIFEST.json'))
        task, version, repo = manifest.get('task'), manifest.get('version'), manifest.get('repo_id')
        require(isinstance(task, str) and SAFE_NAME.fullmatch(task) and isinstance(version, str) and
                SAFE_NAME.fullmatch(version) and isinstance(repo, str) and SAFE_REPO.fullmatch(repo),
                '数据集身份无效。')
        dataset_root = f'datasets/{task}/{version}'
        require(manifest.get('format') == 'so101-transfer-bundle-v1' and
                manifest.get('dataset_root') == dataset_root, '数据包类型或数据集路径不匹配。')
        records = manifest.get('files')
        require(isinstance(records, dict) and set(names) == set(records) | {'BUNDLE_MANIFEST.json', 'README_解包与训练.txt'},
                '数据包清单与内容不一致。')
        for name, record in records.items():
            require(name.startswith(dataset_root + '/') or name.startswith(f'rounds/{task}/{version}/'),
                    f'数据包包含其他任务的文件：{name}')
            require(isinstance(record, dict) and isinstance(record.get('bytes'), int) and record['bytes'] >= 0 and
                    isinstance(record.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', record['sha256']),
                    f'校验清单条目无效：{name}')
        target = Path(tempfile.mkdtemp(prefix=f'so101_{task}_', dir=parent))
        marker = target / 'IMPORT_INCOMPLETE.txt'
        marker.write_text('解包与校验尚未完成，请勿训练。\n', encoding='utf-8')
        print(f'正在解包到新目录：{target}', flush=True)
        try:
            for member in members:
                output = target.joinpath(*PurePosixPath(member.name).parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with tar.extractfile(member) as source, output.open('xb') as dest:
                    while block := source.read(BLOCK):
                        dest.write(block)
                        digest.update(block)
                        size += len(block)
                if member.name in records:
                    expected = records[member.name]
                    require(size == expected['bytes'] and digest.hexdigest() == expected['sha256'],
                            f'解包文件校验失败：{member.name}')
            require((target / dataset_root / 'meta/info.json').is_file(), '解包后缺少数据集元数据。')
            marker.unlink()
        except BaseException:
            print(f'解包未完成；保留目录 {target} 和 IMPORT_INCOMPLETE.txt，请勿训练。', file=sys.stderr)
            raise
    print('SHA-256 和文件校验通过。服务器 LeRobot 仍需读回和冒烟训练。')
    print('在当前服务器终端设置训练输入（复制下列两行）：')
    print('export DS_ROOT=' + shlex.quote(str(target / dataset_root)))
    print('export REPO_ID=' + shlex.quote(repo))
    return target


def main():
    parser = argparse.ArgumentParser(description='校验 SO-101 数据包并解压到一个新的隔离目录。')
    parser.add_argument('archive', help='数据包 .tar 路径；旁边须有同名 .tar.sha256')
    parser.add_argument('--destination', default=str(Path.home() / 'soarm101_dorm' / 'imports'),
                        help='已存在的服务器导入根目录')
    args = parser.parse_args()
    try:
        unpack(Path(args.archive).expanduser(), Path(args.destination).expanduser().resolve())
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f'校验或解包失败：{exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
