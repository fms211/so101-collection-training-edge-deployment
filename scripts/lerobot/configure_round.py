"""Guided changes to round number and target; existing dataset identity is preserved."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile


def validate_values(round_id, episodes):
    if not re.fullmatch(r'r[0-9]{2,}', round_id):
        raise ValueError('轮次需为 r01、r02 等格式')
    if not re.fullmatch(r'[1-9][0-9]*', episodes):
        raise ValueError('条数必须是大于零的整数')


def update_text(text, round_id, episodes):
    validate_values(round_id, episodes)
    for key, value in [('ROUND_ID', round_id), ('EPISODES_THIS_ROUND', episodes)]:
        pattern = re.compile(rf'^{key}=[^\n\r]*$', re.MULTILINE)
        text, count = pattern.subn(f'{key}={shlex.quote(value)}', text)
        if count != 1:
            raise ValueError(f'{key} must appear exactly one time')
    return text


def check_existing_round(directory, round_id, episodes, dataset_id):
    session = directory / 'SESSION.json'
    manifest = directory / 'ROUND.md'
    if session.exists() != manifest.exists():
        raise ValueError(f'incomplete round files: {directory}; preserve and inspect them')
    if session.exists():
        data = json.loads(session.read_text())
        if data.get('round') != round_id or data.get('repo_id') != dataset_id:
            raise ValueError('existing round identity does not match the current dataset')
        if data.get('target_episodes') != int(episodes):
            raise ValueError(f'existing round target is {data.get("target_episodes")}; do not change it')


def main():
    if len(sys.argv) != 2:
        raise ValueError('usage: configure_round.py CONFIG')
    if not sys.stdin.isatty():
        raise ValueError('需要交互式终端')
    path = Path(sys.argv[1])
    original = path.read_text()
    old_round = os.environ['ROUND_ID']
    old_count = os.environ['EPISODES_THIS_ROUND']
    print('只修改轮次编号和本轮目标条数；任务、版本、设备和校准保持原配置。')
    round_id = input(f'轮次 [{old_round}]: ').strip() or old_round
    episodes = input(f'本轮目标条数 [{old_count}]: ').strip() or old_count
    updated = update_text(original, round_id, episodes)
    print(f'拟设置：轮次 {round_id}，目标 {episodes} 条。')
    if input('输入 YES 保存，其他输入取消: ').strip() != 'YES':
        print('已取消，配置未更改。')
        return
    data_root = Path(os.environ['FMS688_DATA'])
    if not data_root.is_dir():
        raise ValueError('数据目录不存在；请先挂载数据盘')
    lock_dir = data_root / 'locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(os.environ['DATASET_ROOT'].encode()).hexdigest() + '.lock'
    with (lock_dir / lock_name).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('此数据集正被使用，请先停止采集或检查') from None
        check_existing_round(Path(os.environ['ROUND_DIR']).parent / round_id, round_id, episodes,
                             os.environ['DATASET_ID'])
        if path.read_text() != original:
            raise ValueError('配置文件已被其他程序修改，请重新操作')
        mode = stat.S_IMODE(path.stat().st_mode)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.round-config-',
                                             encoding='utf-8', delete=False) as temp:
                temp_name = temp.name
                os.fchmod(temp.fileno(), mode)
                temp.write(updated)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    print('配置已保存；采集前仍须通过预检和人工确认。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, EOFError, json.JSONDecodeError) as exc:
        print(f'配置未保存：{exc}', file=sys.stderr)
        sys.exit(1)
