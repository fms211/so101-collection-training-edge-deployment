#!/usr/bin/env python3
"""Select and package one complete, QA-closed local SO-101 dataset version."""

import argparse
import contextlib
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tarfile
from datetime import datetime, timezone


SAFE_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]*$')
SAFE_REPO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$')
ROUND_NAME = re.compile(r'^r[0-9]{2,}$')
BLOCK = 1024 * 1024


class PackageError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise PackageError(message)


def read_json(path):
    try:
        with path.open(encoding='utf-8') as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise PackageError(f'无法读取 JSON：{path}；{exc}') from exc


def regular_files(folder):
    """List a tree without following symlinks or ignoring special files."""
    require(folder.is_dir() and not folder.is_symlink(), f'目录不存在或为符号链接：{folder}')
    result = []
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), f'不允许打包符号链接：{path}')
        if path.is_file():
            result.append(path)
        else:
            require(path.is_dir(), f'不支持特殊文件：{path}')
    return result


def safe_dataset_paths(root, task, version):
    require(SAFE_NAME.fullmatch(task) and SAFE_NAME.fullmatch(version), '任务或版本名称不符合安全规则。')
    for folder in (root / 'datasets', root / 'datasets' / task,
                   root / 'rounds', root / 'rounds' / task):
        require(not folder.is_symlink(), f'不允许任务目录为符号链接：{folder}')
    return root / 'datasets' / task / version, root / 'rounds' / task / version


def discover(root):
    """Include initialized rounds whose dataset directory has not been created yet."""
    choices = set()
    for category in ('datasets', 'rounds'):
        base = root / category
        if not base.is_dir() or base.is_symlink():
            continue
        for task in base.iterdir():
            if not task.is_dir() or task.is_symlink() or not SAFE_NAME.fullmatch(task.name):
                continue
            for version in task.iterdir():
                if version.is_dir() and not version.is_symlink() and SAFE_NAME.fullmatch(version.name):
                    choices.add((task.name, version.name))
    return sorted(choices)


def describe(root, task, version):
    dataset, rounds = safe_dataset_paths(root, task, version)
    info = dataset / 'meta' / 'info.json'
    if not info.is_file():
        return '未生成完整数据集，不能打包'
    try:
        metadata = read_json(info)
        sessions = sorted(rounds.glob('r*/SESSION.json')) if rounds.is_dir() else []
        states = [str(read_json(p).get('status', '未知')) for p in sessions]
        state = '轮次均已关闭（打包前还需检查）' if states and all(s == 'closed' for s in states) else \
                '待采集或审核：' + (', '.join(states) if states else '无轮次记录')
        return f"{metadata.get('total_episodes', '?')} 条 / {metadata.get('total_frames', '?')} 帧；{state}"
    except PackageError:
        return '元数据损坏，不能打包'


@contextlib.contextmanager
def dataset_lock(root, dataset):
    # Same lexical DATASET_ROOT hash and flock protocol as collection.py.
    lock_dir = root / 'locks'
    require(lock_dir.is_dir() and not lock_dir.is_symlink(), f'采集锁目录不存在：{lock_dir}')
    lock_path = lock_dir / (hashlib.sha256(str(dataset).encode()).hexdigest() + '.lock')
    require(not lock_path.is_symlink(), f'锁文件不能是符号链接：{lock_path}')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'r+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PackageError('数据集正在采集或审核，请停止后再打包。') from exc
        yield


def manifest_values(path):
    values = {}
    require(path.is_file() and not path.is_symlink(), f'轮次清单缺失：{path}')
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    return values


def stable_hash(path):
    require(not path.is_symlink(), f'不允许符号链接：{path}')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        while block := stream.read(BLOCK):
            digest.update(block)
        after = os.fstat(stream.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino), f'读取时文件被修改：{path}')
    return digest.hexdigest(), before.st_size


def positive_int(value):
    return type(value) is int and value > 0


def validate_dataset(root, task, version):
    dataset, rounds = safe_dataset_paths(root, task, version)
    require(dataset.is_dir() and not dataset.is_symlink(), '该版本尚未生成数据集，不能作为训练数据打包。')
    require(rounds.is_dir() and not rounds.is_symlink(), '缺少轮次审核目录，不能作为训练数据打包。')
    require(not (rounds / 'DATASET_QUARANTINED.md').exists(), '数据集处于隔离状态，不能打包。')
    files = regular_files(dataset)
    by_relative = {str(path.relative_to(dataset)): path for path in files}
    for name in ('meta/info.json', 'meta/stats.json', 'meta/tasks.parquet'):
        require(name in by_relative, f'缺少数据集文件：{name}；可能尚未保存完成。')
    require(any(p.startswith('meta/episodes/') and p.endswith('.parquet') for p in by_relative), '缺少 episode 元数据。')
    require(any(p.startswith('data/') and p.endswith('.parquet') for p in by_relative), '缺少包含图像的数据 Parquet。')
    require(not any(p.startswith(('images/', 'videos/')) for p in by_relative),
            '发现临时图片或视频文件；请保留现场并检查，不能作为已完成的图像数据集打包。')
    info = read_json(dataset / 'meta/info.json')
    require(info.get('codebase_version') == 'v3.0' and info.get('robot_type') == 'so101_follower',
            '数据集格式或机械臂类型不符合 SO-101 LeRobot v3.0。')
    require(positive_int(info.get('total_episodes')) and positive_int(info.get('total_frames')) and positive_int(info.get('fps')),
            '数据集没有有效轨迹、帧数或帧率。')
    features = info.get('features', {})
    for key in ('action', 'observation.state'):
        require(features.get(key, {}).get('shape') == [6], f'{key} 不是六维 SO-101 数据。')
    for key in ('observation.images.top', 'observation.images.wrist'):
        feature = features.get(key, {})
        shape = feature.get('shape', [])
        require(feature.get('dtype') == 'image' and len(shape) == 3 and shape[2] == 3 and
                all(positive_int(v) for v in shape), f'{key} 不是有效的 RGB 图像特征。')

    round_dirs = sorted((p for p in rounds.iterdir() if ROUND_NAME.fullmatch(p.name)),
                        key=lambda p: int(p.name[1:]))
    require(round_dirs, '没有轮次审核记录。')
    last_end = 0
    fingerprint = None
    repo_id = None
    selected_round_files = []
    last_validation = None
    for folder in round_dirs:
        require(folder.is_dir() and not folder.is_symlink(), f'轮次目录无效：{folder}')
        expected = {name: folder / name for name in ('ROUND.md', 'SESSION.json', 'QA.csv', 'VALIDATION.json')}
        require(all(p.is_file() and not p.is_symlink() for p in expected.values()), f'{folder.name} 缺少完整审核记录。')
        state = read_json(expected['SESSION.json'])
        manifest = manifest_values(expected['ROUND.md'])
        require(state.get('round') == folder.name and state.get('status') == 'closed', f'{folder.name} 尚未关闭。')
        require(manifest.get('round') == folder.name and manifest.get('status') == 'closed' and
                manifest.get('quality') == 'pass', f'{folder.name} 未通过质检。')
        require(manifest.get('task') == task and manifest.get('version') == version and
                manifest.get('dataset_root') == str(dataset), f'{folder.name} 数据集路径或身份不一致。')
        this_repo = state.get('repo_id')
        require(isinstance(this_repo, str) and SAFE_REPO.fullmatch(this_repo) and
                manifest.get('dataset_id') == this_repo, f'{folder.name} 数据集 ID 无效。')
        if repo_id is None:
            repo_id = this_repo
        require(repo_id == this_repo, '各轮数据集 ID 不一致。')
        this_fingerprint = state.get('fingerprint')
        require(isinstance(this_fingerprint, str) and re.fullmatch(r'[a-f0-9]{64}', this_fingerprint),
                f'{folder.name} 缺少有效的采集配置指纹。')
        if fingerprint is None:
            fingerprint = this_fingerprint
        require(fingerprint == this_fingerprint, '各轮采集配置指纹不一致。')
        start, count = state.get('start_episode'), state.get('target_episodes')
        require(type(start) is int and start == last_end and positive_int(count) and
                state.get('saved_episodes') == count, f'{folder.name} 轨迹范围或保存数量不一致。')
        with expected['QA.csv'].open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        try:
            episode_ids = [int(row['episode']) for row in rows]
            passed = all(row['result'] == 'pass' and row['privacy'] == 'pass' and row['item'].strip() for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise PackageError(f'{folder.name} 的 QA.csv 格式错误。') from exc
        require(len(rows) == count and set(episode_ids) == set(range(start, start + count)) and passed,
                f'{folder.name} 的逐条质量或隐私审核未通过。')
        last_end = start + count
        last_validation = read_json(expected['VALIDATION.json'])
        selected_round_files.extend(expected.values())
    require(last_end == info['total_episodes'], '轮次审核数量与数据集轨迹总数不一致。')
    require(last_validation.get('total_episodes') == last_end and isinstance(last_validation.get('files'), dict),
            '最新轮次的数据校验记录不完整。')
    seal = rounds / 'DATASET_SEALED.md'
    if seal.exists():
        require(seal.is_file() and not seal.is_symlink(), '封版记录无效。')
        selected_round_files.append(seal)
    return dataset, by_relative, selected_round_files, last_validation['files'], info, repo_id


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        self.count += len(data)
        return data


def add_checked(tar, path, name, expected_hash, expected_size):
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        require(before.st_size == expected_size and not path.is_symlink(), f'文件发生变化：{path}')
        entry = tarfile.TarInfo(name)
        entry.size, entry.mode, entry.mtime = before.st_size, 0o644, int(before.st_mtime)
        reader = HashingReader(stream)
        tar.addfile(entry, reader)
        after = os.fstat(stream.fileno())
        require(reader.count == expected_size and reader.digest.hexdigest() == expected_hash and
                (before.st_size, before.st_mtime_ns, before.st_ino) ==
                (after.st_size, after.st_mtime_ns, after.st_ino), f'打包时文件发生变化：{path}')


def add_bytes(tar, name, data):
    entry = tarfile.TarInfo(name)
    entry.size, entry.mode = len(data), 0o644
    tar.addfile(entry, io.BytesIO(data))


def verify_archive(path, expected):
    with tarfile.open(path, 'r:') as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)) and set(names) == set(expected), '归档文件列表与清单不一致。')
        for member in members:
            require(member.isfile(), f'归档中存在非普通文件：{member.name}')
            stream = tar.extractfile(member)
            digest = hashlib.sha256()
            size = 0
            while block := stream.read(BLOCK):
                digest.update(block)
                size += len(block)
            wanted_hash, wanted_size = expected[member.name]
            require(size == wanted_size and digest.hexdigest() == wanted_hash, f'归档校验失败：{member.name}')


def create_package(root, task, version, output):
    dataset, rounds = safe_dataset_paths(root, task, version)
    require(dataset.is_dir(), '该版本尚未生成数据集，不能打包。')
    require(output.is_dir(), f'输出目录不存在：{output}')
    out_resolved = output.resolve()
    require(not out_resolved.is_relative_to(dataset.resolve()) and not out_resolved.is_relative_to(rounds.resolve()),
            '输出目录不能位于源数据集或轮次目录内。')
    with dataset_lock(root, dataset):
        dataset, dataset_files, round_files, qc_hashes, info, repo = validate_dataset(root, task, version)
        print('正在计算数据校验值，数据较大时可能需要较长时间……', flush=True)
        sources = {}
        for relative, path in sorted(dataset_files.items()):
            name = f'datasets/{task}/{version}/{relative}'
            digest, size = stable_hash(path)
            sources[name] = (path, digest, size)
        current_snapshot = {relative: sources[f'datasets/{task}/{version}/{relative}'][1]
                            for relative in dataset_files if relative.split('/', 1)[0] in ('meta', 'data', 'images', 'videos')}
        require(current_snapshot == qc_hashes, '数据在最近一次审核后发生变化，请重新执行采集助手的检查和审核。')
        for path in sorted(round_files):
            name = f'rounds/{task}/{version}/{path.relative_to(rounds)}'
            digest, size = stable_hash(path)
            sources[name] = (path, digest, size)
        file_size = sum(x[2] for x in sources.values())
        required = file_size + len(sources) * 4096 + 64 * 1024 * 1024
        require(shutil.disk_usage(output).free >= required,
                f'输出空间不足：至少需要约 {required / 1024**3:.2f} GiB。')
        timestamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
        basename = f'so101_{task}_{version}_{timestamp}_{secrets.token_hex(3)}.tar'
        final = output / basename
        temp = output / ('.' + basename + '.partial')
        checksum_final = output / (basename + '.sha256')
        checksum_temp = output / ('.' + basename + '.sha256.partial')
        require(not final.exists() and not temp.exists() and not checksum_final.exists() and not checksum_temp.exists(),
                '输出文件名已存在，未覆盖任何文件。')
        manifest = {
            'format': 'so101-transfer-bundle-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
            'task': task, 'version': version, 'repo_id': repo,
            'dataset_root': f'datasets/{task}/{version}', 'episodes': info['total_episodes'],
            'frames': info['total_frames'], 'fps': info['fps'],
            'files': {name: {'sha256': digest, 'bytes': size} for name, (_, digest, size) in sources.items()},
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
        readme_bytes = (f'SO-101 LeRobot v3 image dataset\n任务: {task}\n版本: {version}\n'
                        f'数据集 ID: {repo}\n解包后的训练数据目录: datasets/{task}/{version}\n'
                        '请先核对 .sha256，再在新的空目录解包；在服务器用现有 LeRobot 环境读取并冒烟训练。\n'
                        '采集机 QA 已通过不代表服务器兼容性已验证。\n').encode()
        expected = {name: (digest, size) for name, (_, digest, size) in sources.items()}
        for name, data in [('BUNDLE_MANIFEST.json', manifest_bytes), ('README_解包与训练.txt', readme_bytes)]:
            expected[name] = (hashlib.sha256(data).hexdigest(), len(data))
        print(f'正在打包 {len(sources)} 个文件，原始大小约 {file_size / 1024**3:.2f} GiB……', flush=True)
        try:
            with temp.open('xb') as raw, tarfile.open(fileobj=raw, mode='w') as tar:
                for name, (path, digest, size) in sources.items():
                    print(f'  {name}', flush=True)
                    add_checked(tar, path, name, digest, size)
                add_bytes(tar, 'BUNDLE_MANIFEST.json', manifest_bytes)
                add_bytes(tar, 'README_解包与训练.txt', readme_bytes)
            require({str(p.relative_to(dataset)) for p in regular_files(dataset)} == set(dataset_files),
                    '打包期间数据文件列表发生变化。')
            print('正在重新读取归档并逐文件校验……', flush=True)
            verify_archive(temp, expected)
            archive_hash, _ = stable_hash(temp)
            with checksum_temp.open('x', encoding='ascii') as stream:
                stream.write(f'{archive_hash}  {basename}\n')
            require(not final.exists() and not checksum_final.exists(), '输出文件名已存在，未覆盖任何文件。')
            temp.rename(final)
            checksum_temp.rename(checksum_final)
        finally:
            for path in (temp, checksum_temp):
                if path.exists():
                    path.unlink()
    return final, checksum_final, repo


def main():
    parser = argparse.ArgumentParser(description='交互选择 SO-101 任务与版本，打包已完成审核的完整数据集。')
    parser.add_argument('--data-root', default=str(Path.home() / 'fms688_data'), help='采集机数据根目录，需与采集配置路径一致')
    parser.add_argument('--list', action='store_true', help='只列出候选数据集，不打包')
    options = parser.parse_args()
    root = Path(os.path.abspath(os.path.expanduser(options.data_root)))
    require(root.is_dir(), f'数据根目录不存在，请先挂载 E 盘：{root}')
    while True:
        choices = discover(root)
        print(f'\nSO-101 数据打包工具\n数据根目录：{root}')
        if not choices:
            print('尚无任务版本；采集、回放和质量审核完成后再来打包。')
            return
        for index, (task, version) in enumerate(choices, 1):
            print(f'{index}. {task} / {version} — {describe(root, task, version)}')
        if options.list:
            return
        print('0. 退出')
        try:
            answer = input('选择要打包的完整数据集编号：').strip()
            if answer == '0':
                return
            require(answer.isdecimal() and 1 <= int(answer) <= len(choices), '请输入列表中的编号。')
            task, version = choices[int(answer) - 1]
            default_output = Path(__file__).absolute().parent / '打包结果'
            dest = input(f'输出目录（回车使用 {default_output}）：').strip()
            output = Path(os.path.abspath(os.path.expanduser(dest))) if dest else default_output
            if not dest:
                output.mkdir(exist_ok=True)
            print(f'将检查并打包：{task} / {version}；输出：{output}')
            if input('输入 YES 开始，其余输入取消：').strip() != 'YES':
                print('已取消。')
                continue
            archive, checksum, repo = create_package(root, task, version, output)
            print(f'\n打包并校验完成：\n  数据包：{archive}\n  校验文件：{checksum}\n  数据集 ID：{repo}')
            print('把数据包和校验文件一起复制到服务器，按工具目录中的 README 操作。')
        except PackageError as exc:
            print(f'未打包：{exc}', file=sys.stderr)
        except (OSError, tarfile.TarError) as exc:
            print(f'打包失败，源数据未更改：{exc}', file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print('\n已退出。')
            return


if __name__ == '__main__':
    try:
        main()
    except PackageError as exc:
        print(f'错误：{exc}', file=sys.stderr)
        sys.exit(1)
