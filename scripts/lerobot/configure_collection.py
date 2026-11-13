"""Select a dated task and round before recording; never create a dataset here."""
import datetime
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

DESCRIPTION = 'Pick up small objects and place them in the container.'


def validate_task(task):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', task):
        raise ValueError('任务名称只能使用小写英文字母、数字、下划线和连字符')


def dated_tasks(root):
    base = root / 'rounds'
    if not base.is_dir():
        return []
    return sorted((p for task in base.iterdir() if task.is_dir() for p in task.iterdir()
                   if p.is_dir() and re.fullmatch(r'[0-9]{8}_[a-z0-9][a-z0-9_-]*', p.name)
                   and p.name[9:] == task.name), reverse=True)


def replace_fields(text, values):
    for key, value in values.items():
        text, count = re.subn(rf'^{key}=[^\r\n]*$', lambda m: key + '=' + shlex.quote(value), text, flags=re.M)
        if count != 1:
            raise ValueError(f'配置项 {key} 必须且只能出现一次')
    return text


def round_info(directory):
    rounds = sorted((p for p in directory.glob('r[0-9]*') if p.is_dir()), key=lambda p: int(p.name[1:]))
    states = []
    for folder in rounds:
        session, manifest = folder / 'SESSION.json', folder / 'ROUND.md'
        if not session.is_file() or not manifest.is_file():
            raise ValueError(f'轮次文件不完整，请保留并检查：{folder}')
        state = json.loads(session.read_text())
        if state.get('round') != folder.name:
            raise ValueError(f'轮次信息不匹配：{folder}')
        states.append((folder, state))
    return states


def task_description(folder):
    manifests = sorted(folder.glob('r*/ROUND.md'))
    if not manifests:
        raise ValueError('已有任务没有轮次清单，请先检查目录')
    values = [line.split('=', 1)[1] for line in manifests[0].read_text().splitlines() if line.startswith('task_description=')]
    if len(values) != 1 or not values[0].strip():
        raise ValueError('任务描述缺失或不明确')
    return values[0]


def main(config):
    if not sys.stdin.isatty():
        raise ValueError('需要交互式终端')
    path = Path(config)
    original = path.read_text()
    root = Path(os.environ['FMS688_DATA'])
    if not root.is_dir():
        raise ValueError('数据盘未挂载或数据目录不存在')
    choices = dated_tasks(root)
    print('选择已有日期任务，或新建今天的任务：')
    for i, folder in enumerate(choices, 1):
        print(f'{i}. {folder.name}')
    selection = input('输入编号；新任务按回车: ').strip()
    if selection:
        if not selection.isdigit() or not 1 <= int(selection) <= len(choices):
            raise ValueError('无效的任务编号')
        folder = choices[int(selection) - 1]
        task, version = folder.parent.name, folder.name
        description = task_description(folder)
        states = round_info(folder)
        if not states:
            raise ValueError('任务目录没有完整轮次')
        last, state = states[-1]
        expected_repo = os.environ.get('HF_REPO_ID') or f"{os.environ['DATASET_NAMESPACE']}/so101_{version}"
        if state.get('repo_id') != expected_repo:
            raise ValueError(f'已有组的数据集 ID 为 {state.get("repo_id")}，与当前配置 {expected_repo} 不一致；请恢复原 HF_REPO_ID 或使用新任务')
        if state.get('status') == 'closed':
            round_id = f'r{int(last.name[1:]) + 1:02d}'
            count = input('新一组轨迹条数 [40]: ').strip() or '40'
        else:
            round_id = last.name
            count = str(state['target_episodes'])
            print(f'继续未完成组 {round_id}，原目标 {count} 条。')
    else:
        today = datetime.date.today().strftime('%Y%m%d')
        task = input('新任务英文名称 [pick_to_container]: ').strip() or 'pick_to_container'
        validate_task(task)
        version = f'{today}_{task}'
        folder = root / 'rounds' / task / version
        if folder.exists() or (root / 'datasets' / task / version).exists():
            raise ValueError('今天同名任务已存在，请选择已有任务继续')
        description = input(f'任务描述 [{DESCRIPTION}]: ').strip() or DESCRIPTION
        if '\n' in description or '\r' in description:
            raise ValueError('任务描述须为单行')
        round_id = 'r01'
        count = input('本组轨迹条数 [40]: ').strip() or '40'
    if not re.fullmatch(r'[1-9][0-9]*', count):
        raise ValueError('条数必须为大于零的整数')
    values = {'TASK_SLUG': task, 'TASK_DESCRIPTION': description, 'DATASET_VERSION': version,
              'ROUND_ID': round_id, 'EPISODES_THIS_ROUND': count}
    updated = replace_fields(original, values)
    dataset = root / 'datasets' / task / version
    print(f'日期任务: {version}；组: {round_id}；目标: {count} 条\n数据: {dataset}\n轮次记录: {folder / round_id}')
    if input('输入 YES 确认，其他取消: ').strip() != 'YES':
        print('已取消。')
        return False
    lockdir = root / 'locks'
    lockdir.mkdir(parents=True, exist_ok=True)
    with (lockdir / (hashlib.sha256(str(dataset).encode()).hexdigest() + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('数据集正在使用') from None
        if path.read_text() != original:
            raise ValueError('配置已改变，请重试')
        if not selection and (folder.exists() or dataset.exists()):
            raise ValueError('任务已被创建，请重试')
        if selection and round_info(folder) != states:
            raise ValueError('轮次状态已改变，请重新选择')
        mode = stat.S_IMODE(path.stat().st_mode)
        name = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.collection-config-', delete=False) as temp:
                name = temp.name
                os.fchmod(temp.fileno(), mode)
                temp.write(updated)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(name, path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
    print('采集配置已保存。')
    return True


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('需要配置文件路径')
        sys.exit(0 if main(sys.argv[1]) else 1)
    except (ValueError, OSError, KeyError, EOFError, json.JSONDecodeError) as exc:
        print(f'未开始采集：{exc}', file=sys.stderr)
        sys.exit(1)
