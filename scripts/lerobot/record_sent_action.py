"""LeRobot 0.6.1 recording: persist the follower's actually sent action."""
import importlib.metadata
import json
import os
import sys
from functools import wraps
from pathlib import Path


def install(record_module):
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('This recording adapter requires LeRobot 0.6.1; review it before upgrading.')
    source = Path(record_module.__file__).read_text(encoding='utf-8')
    if '_sent_action = robot.send_action(robot_action_to_send)' not in source or \
       'build_dataset_frame(dataset.features, action_values, prefix=ACTION)' not in source:
        raise RuntimeError('LeRobot record loop changed; refuse to record until the adapter is reviewed.')
    original_loop = record_module.record_loop
    original_frame = record_module.build_dataset_frame

    @wraps(original_loop)
    def loop(*args, **kwargs):
        robot = kwargs.get('robot', args[0] if args else None)
        if robot is None:
            raise RuntimeError('Recording robot is missing.')
        original_send = robot.send_action
        pending = []
        dataset = kwargs.get('dataset')
        if dataset is not None and os.environ.get('ROUND_DIR'):
            try:
                state = json.loads((Path(os.environ['ROUND_DIR']) / 'SESSION.json').read_text())
                saved = dataset.meta.total_episodes - state['start_episode']
                target = state['target_episodes']
                if target > 0 and 0 <= saved <= target:
                    print(f'进度 [本组已保存] {saved * 100 // target}% ({saved}/{target} 条)，当前示教尚未保存。', flush=True)
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                print('本组进度暂不可用；请查看采集日志。', flush=True)

        def send(action):
            sent = original_send(action)
            if not isinstance(sent, dict) or set(sent) != set(action):
                raise RuntimeError('Follower did not return the complete sent action; recording stopped.')
            pending[:] = [dict(sent)]
            return sent

        def frame(features, values, prefix):
            if prefix == record_module.ACTION:
                if not pending:
                    raise RuntimeError('No sent action available for this frame; recording stopped.')
                values = pending.pop()
            return original_frame(features, values, prefix=prefix)

        robot.send_action = send
        record_module.build_dataset_frame = frame
        try:
            return original_loop(*args, **kwargs)
        finally:
            robot.send_action = original_send
            record_module.build_dataset_frame = original_frame

    record_module.record_loop = loop


def main():
    from lerobot.scripts import lerobot_record
    install(lerobot_record)
    print('SO101 recorder: dataset action = actual follower sent action.', flush=True)
    if sys.argv[1:] == ['--check-adapter']:
        return
    from record_control import init_listener
    lerobot_record.init_keyboard_listener = init_listener
    lerobot_record.main()


if __name__ == '__main__':
    main()
