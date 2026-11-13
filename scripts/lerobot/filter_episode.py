"""Create a separate local LeRobot dataset without one selected episode."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import collection


def delete_current(index):
    """Edit the latest round only, keeping a backup and an interruption guard."""
    source = collection.root()
    folder = collection.round_dir()
    with collection.lock():
        collection.writable()
        state = collection.session()
        if state.get('status') not in ('ready', 'needs_review', 'closed'):
            raise ValueError('当前组未安全结束或需要恢复，请先检查会话。')
        info = collection.validate()
        count = int(info['total_episodes'])
        rounds = sorted((p for p in folder.parent.glob('r*/SESSION.json')
                         if p.parent.name[1:].isdigit()), key=lambda p: int(p.parent.name[1:]))
        if not rounds or rounds[-1].parent != folder:
            raise ValueError('只能删除当前最新一组的轨迹。')
        if any(folder.parent.glob('r*/UPLOAD.json')):
            raise ValueError('此数据集已有上传记录，请先协调远端版本。')
        if count < 2 or not state['start_episode'] <= index < count:
            raise ValueError('请选择当前组内的轨迹，且至少保留一条。')
        if count - state['start_episode'] > state['target_episodes']:
            raise ValueError('当前组条数不一致，请先检查。')
        before = collection.snapshot()
        backup = Path(os.environ['FMS688_DATA']) / 'backups' / ('episode-delete-' + str(time.time_ns()))
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copytree(folder, backup / 'round')
        stage = source.parent / ('.edit-' + str(time.time_ns()))
        with collection.waiting('生成编辑后的数据集'):
            subprocess.run(['lerobot-edit-dataset', f'--repo_id={os.environ["DATASET_ID"]}', f'--root={source}',
                            f'--new_repo_id={os.environ["DATASET_ID"]}', f'--new_root={stage}',
                            '--operation.type=delete_episodes', f'--operation.episode_indices=[{index}]',
                            '--push_to_hub=false'], check=True)
        if collection.snapshot() != before:
            raise ValueError(f'原始数据变化；保留临时副本 {stage}，请检查。')
        old_root = os.environ['DATASET_ROOT']
        try:
            os.environ['DATASET_ROOT'] = str(stage)
            if collection.validate()['total_episodes'] != count - 1:
                raise ValueError('编辑后轨迹数量不正确。')
        finally:
            os.environ['DATASET_ROOT'] = old_root
        marker = Path(os.environ['DATASET_QUARANTINE'])
        marker.write_text(f'轨迹删除进行中。原数据备份：{backup}/dataset\n轮次备份：{backup}/round\n暂存：{stage}\n')
        source.rename(backup / 'dataset')
        stage.rename(source)
        state['saved_episodes'] = count - 1 - state['start_episode']
        state['status'] = 'needs_review'
        state.pop('closed_at', None)
        state['edited_at'] = collection.now()
        collection.write_json(folder / 'SESSION.json', state)
        with (folder / 'ROUND.md').open('a') as stream:
            stream.write(f'quality=pending\nstatus=needs_review\nedited_at={collection.now()}\n')
        for name in ('QA.csv', 'VALIDATION.json'):
            (folder / name).unlink(missing_ok=True)
        if collection.validate()['total_episodes'] != count - 1:
            raise ValueError('替换后的数据集验证失败，隔离保护仍生效。')
        marker.unlink()
        return backup


def main():
    if not sys.stdin.isatty():
        raise ValueError('需要交互式终端。')
    mode = input('选择 1 删除当前组轨迹并继续采集，2 生成独立副本，其他取消: ').strip()
    if mode == '1':
        raw = input('输入当前组要删除的轨迹编号（从 0 开始）: ').strip()
        if not raw.isdigit():
            raise ValueError('轨迹编号无效。')
        print('会备份数据并删除该轨迹，重置当前组审核；后续轨迹编号可能变化。')
        if input('确认删除并重新审核，输入 DELETE: ').strip() != 'DELETE':
            print('已取消。')
            return
        backup = delete_current(int(raw))
        print(f'删除并校验完成，原始备份：{backup}；请先使用菜单 4 重新检查，再续采或审核。')
        return
    if mode != '2':
        print('已取消。')
        return
    source = collection.root()
    with collection.lock():
        collection.session()
        info = collection.validate()
        count = int(info['total_episodes'])
        if count < 2:
            raise ValueError('至少需要两条已保存轨迹，不能删除全部轨迹。')
        raw = input(f'输入要从副本中去掉的轨迹编号（0 到 {count - 1}）: ').strip()
        if not raw.isdigit() or int(raw) >= count:
            raise ValueError('轨迹编号无效。')
        index = int(raw)
        output = Path(os.environ['FMS688_DATA']) / 'exports' / f"filtered_{os.environ['DATASET_VERSION']}_{time.time_ns()}"
        owner = os.environ['DATASET_ID'].split('/')[0]
        repo = f'{owner}/filtered_{time.time_ns()}'
        if output.exists() or source.resolve() == output.resolve():
            raise ValueError('输出目录已存在或与原始数据相同。')
        print(f'原数据：{source}\n去掉编号：{index}\n副本：{output}\n副本 ID：{repo}')
        print('副本会重新编号；原数据和原轮次不变，副本不能直接在原轮次中继续采集或上传。')
        if input('确认生成本地副本，输入 COPY: ').strip() != 'COPY':
            print('已取消。')
            return
        before = collection.snapshot()
        with collection.waiting('生成轨迹筛选副本'):
            subprocess.run(['lerobot-edit-dataset', f'--repo_id={os.environ["DATASET_ID"]}', f'--root={source}',
                            f'--new_repo_id={repo}', f'--new_root={output}', '--operation.type=delete_episodes',
                            f'--operation.episode_indices=[{index}]', '--push_to_hub=false'], check=True)
        if collection.snapshot() != before:
            raise ValueError('原始数据发生变化；请暂停并检查。')
        result = json.loads((output / 'meta/info.json').read_text())
        if result.get('total_episodes') != count - 1:
            raise ValueError(f'副本轨迹数不符，请保留并检查：{output}')
        print(f'副本已生成：{output}\n轨迹数量：{count} → {count - 1}；请单独回放核对。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'未完成：{exc}', file=sys.stderr)
        sys.exit(1)
