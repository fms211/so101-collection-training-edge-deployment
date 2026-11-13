"""Host collection tools. Motor commands only run via explicit --confirm-physical."""
import argparse
import contextlib
import csv
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone


def env(name):
    return os.environ[name]


def now():
    return datetime.now(timezone.utc).isoformat()


def root():
    return Path(env('DATASET_ROOT'))


def round_dir():
    return Path(env('ROUND_DIR'))


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Progress:
    """Report measured work, with a separate percentage for each stage."""
    def __init__(self, label, total, unit):
        self.label, self.total, self.unit = label, total, unit
        self.started = time.monotonic()
        self.last_percent = -1
        self.last_time = 0.0

    def update(self, value):
        if self.total <= 0:
            return
        value = min(value, self.total)
        percent = int(value * 100 / self.total)
        now_time = time.monotonic()
        if value != self.total and percent == self.last_percent and now_time - self.last_time < 10:
            return
        self.last_percent, self.last_time = percent, now_time
        filled = percent // 5
        bar = '#' * filled + '-' * (20 - filled)
        print(f'进度 [{self.label}] [{bar}] {percent}% ({value}/{self.total} {self.unit})，已用 {now_time-self.started:.0f} 秒', flush=True)


@contextlib.contextmanager
def waiting(label):
    """Indeterminate work must not pretend to know its completion percentage."""
    done = threading.Event()
    started = time.monotonic()
    print(f'进行中 [{label}]：正在等待，无法估算百分比。', flush=True)
    def report():
        while not done.wait(10):
            print(f'进行中 [{label}]：已用 {time.monotonic()-started:.0f} 秒，仍在等待。', flush=True)
    thread = threading.Thread(target=report, daemon=True)
    thread.start()
    try:
        yield
    except BaseException:
        raise
    else:
        print(f'完成 [{label}]：耗时 {time.monotonic()-started:.0f} 秒。', flush=True)
    finally:
        done.set()
        thread.join()


def count():
    path = root() / 'meta/info.json'
    if not path.exists():
        require(not root().exists(), 'Dataset directory exists without metadata. Preserve it and diagnose; do not delete automatically.')
        return 0
    return int(read_json(path)['total_episodes'])


def fingerprint():
    names = ('DATASET_ID', 'TASK_SLUG', 'TASK_DESCRIPTION', 'DATASET_VERSION', 'FPS',
             'FOLLOWER_PORT', 'LEADER_PORT', 'FOLLOWER_ID', 'LEADER_ID', 'TOP_CAMERA',
             'WRIST_CAMERA', 'TOP_WIDTH', 'TOP_HEIGHT', 'WRIST_WIDTH', 'WRIST_HEIGHT',
             'TOP_FOURCC', 'WRIST_FOURCC', 'CALIBRATION_ROOT')
    values = {n: env(n) for n in names}
    values['dataset_storage'] = 'images'
    for folder, ident in [('robots/so_follower', 'FOLLOWER_ID'), ('teleoperators/so_leader', 'LEADER_ID')]:
        path = Path(env('CALIBRATION_ROOT')) / folder / (env(ident) + '.json')
        values[ident + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else 'missing'
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def writable():
    require(not Path(env('DATASET_SEAL')).exists(), 'Dataset is sealed; recording is forbidden.')
    require(not Path(env('DATASET_QUARANTINE')).exists(), 'Dataset is quarantined.')


def require_physical_clearance():
    hold = Path(env('FMS688_DATA')) / 'PHYSICAL_SAFETY_HOLD.md'
    require(not hold.exists(), f'PHYSICAL_SAFETY_HOLD: {hold}; resolve the recorded incident before physical operation.')


def authorize_incident_read():
    hold = Path(env('FMS688_DATA')) / 'PHYSICAL_SAFETY_HOLD.md'
    require(hold.is_file(), 'Incident read is only available while an incident hold is present.')
    require(sys.stdin.isatty(), 'Incident read requires an interactive terminal and onsite operator.')
    print('事故保护仍生效。本次只读寄存器，不更改位置或力矩；上电本身可能导致运动。')
    require(input('确认已检查现场、可立即断电且同意只读检查，输入 READ: ').strip() == 'READ',
            'Incident read not confirmed.')


@contextlib.contextmanager
def lock():
    directory = Path(env('FMS688_DATA')) / 'locks'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(str(root()).encode()).hexdigest() + '.lock')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another recording/review/upload is using this dataset.') from None
        yield


def init():
    writable()
    path = round_dir() / 'SESSION.json'
    require(not path.exists(), 'Session already exists.')
    start = count()
    prior = []
    for other in round_dir().parent.glob('r*/SESSION.json'):
        state = read_json(other)
        require(state['status'] == 'closed', f'Close previous round first: {other}')
        require(state['fingerprint'] == fingerprint(), 'Hardware/task changed within this dataset version.')
        prior.append(state)
    if env('ROUND_ID') == 'r01':
        require(start == 0 and not root().exists(), 'r01 requires a new dataset path.')
    else:
        require(prior and start > 0, 'A later round requires a closed earlier round and real dataset.')
    write_json(path, {'repo_id': env('DATASET_ID'), 'round': env('ROUND_ID'), 'start_episode': start,
                      'target_episodes': int(env('EPISODES_THIS_ROUND')), 'saved_episodes': 0,
                      'fingerprint': fingerprint(), 'status': 'ready', 'created_at': now()})


def session():
    state = read_json(round_dir() / 'SESSION.json')
    require(state['repo_id'] == env('DATASET_ID') and state['round'] == env('ROUND_ID'), 'Session identity mismatch.')
    require(state['fingerprint'] == fingerprint(), 'Configuration changed since init; use a new version or restore it.')
    require(state['target_episodes'] == int(env('EPISODES_THIS_ROUND')), 'Do not change target count within a round.')
    return state


def snapshot():
    files = {}
    paths = []
    for folder in ('meta', 'data', 'images', 'videos'):
        for path in sorted((root() / folder).rglob('*')):
            if path.is_file():
                require(not path.is_symlink(), f'Symlink not allowed: {path}')
                paths.append(path)
    total_bytes = sum(p.stat().st_size for p in paths)
    progress = Progress('文件校验', total_bytes, '字节')
    progress.update(0)
    completed = 0
    for path in paths:
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
                completed += len(block)
                progress.update(completed)
        files[str(path.relative_to(root()))] = h.hexdigest()
    require(files, 'No dataset files.')
    return files


def validate(allow_empty=False):
    """Read every frame and both camera images through the installed LeRobot reader."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    info = read_json(root() / 'meta/info.json')
    require(info['fps'] == int(env('FPS')), 'FPS mismatch.')
    for camera, width, height in [('top', 'TOP_WIDTH', 'TOP_HEIGHT'), ('wrist', 'WRIST_WIDTH', 'WRIST_HEIGHT')]:
        feature = info['features'].get('observation.images.' + camera)
        require(feature is not None and feature['dtype'] == 'image', f'Missing image camera {camera}')
        require(feature['shape'] == [int(env(height)), int(env(width)), 3], f'Wrong dimensions: {camera}')
    require('action' in info['features'] and 'observation.state' in info['features'], 'Missing action/state.')
    if info.get('total_episodes') == 0 and info.get('total_frames') == 0:
        require(allow_empty, 'Empty dataset has no episodes to review.')
        require(info.get('total_tasks') == 0, 'Empty dataset has inconsistent task metadata; preserve it.')
        files = set()
        for path in root().rglob('*'):
            require(not path.is_symlink(), f'Empty dataset contains an extra symlink: {path}; preserve it.')
            if path.is_file():
                files.add(str(path.relative_to(root())))
        require(files == {'meta/info.json'}, 'Empty dataset has extra or orphan files; preserve and inspect them.')
        print('EMPTY DATASET VERIFIED: no episodes, frames, or extra files; resume without deleting it.')
        return info
    require(list((root() / 'data').rglob('*.parquet')), 'No Parquet data containing image features.')
    require(not any(path.is_file() for path in (root() / 'videos').rglob('*')),
            'Unexpected video files in image dataset.')
    with waiting('加载数据集与准备读取缓存'):
        ds = LeRobotDataset(env('DATASET_ID'), root=root())
    require(len(ds) == info['total_frames'] and len(ds) > 0, 'Frame count mismatch/empty dataset.')
    import numpy as np
    episodes = set()
    progress = Progress('逐帧检查动作与双相机', len(ds), '帧')
    progress.update(0)
    for index in range(len(ds)):
        frame = ds[index]
        episodes.add(int(frame['episode_index']))
        require(frame['task'] == env('TASK_DESCRIPTION'), 'Task description mismatch.')
        for key in ('action', 'observation.state'):
            require(np.isfinite(np.asarray(frame[key])).all(), f'Invalid values: frame {index} {key}')
        for camera, width, height in [('top', 'TOP_WIDTH', 'TOP_HEIGHT'), ('wrist', 'WRIST_WIDTH', 'WRIST_HEIGHT')]:
            image = np.asarray(frame['observation.images.' + camera])
            require(image.shape == (3, int(env(height)), int(env(width))), f'Invalid {camera} image: frame {index}')
            require(np.isfinite(image).all(), f'Invalid {camera} pixels: frame {index}')
        progress.update(index + 1)
    require(episodes == set(range(info['total_episodes'])), 'Episode indices/count mismatch.')
    print(f'VALIDATED: {len(ds)} frames, {len(episodes)} episodes; both camera image streams read.')
    return info


def camera_configs():
    from lerobot.cameras.opencv import OpenCVCameraConfig
    return {name: OpenCVCameraConfig(index_or_path=env(prefix + '_CAMERA'),
                width=int(env(prefix + '_WIDTH')), height=int(env(prefix + '_HEIGHT')),
                fps=int(env('FPS')), fourcc=env(prefix + '_FOURCC') or None)
            for name, prefix in [('top', 'TOP'), ('wrist', 'WRIST')]}


def camera_identity():
    paths = [Path(env('TOP_CAMERA')), Path(env('WRIST_CAMERA'))]
    require(all(p.exists() for p in paths), 'Connect the external top and wrist cameras; placeholders are not usable.')
    require(paths[0].resolve() != paths[1].resolve(), 'Both camera names resolve to the same device.')
    for p in paths:
        props = subprocess.check_output(['udevadm', 'info', '-q', 'property', '-n', str(p)], text=True)
        require('ID_VENDOR_ID=5959' not in props or 'ID_MODEL_ID=0107' not in props,
                'FHD Camera 5959:0107 is the built-in webcam, not a robot camera.')


def cameras(seconds=10, preview=False):
    from lerobot.cameras.opencv import OpenCVCamera
    import cv2
    camera_identity()
    devices = {n: OpenCVCamera(c) for n, c in camera_configs().items()}
    counts = {n: 0 for n in devices}
    stamps = {n: None for n in devices}
    if preview:
        from lerobot.utils.visualization_utils import init_visualization
        import rerun as rr
        init_visualization('rerun', session_name='SO101 camera identity check')
    try:
        for name, dev in devices.items():
            with waiting(f'连接相机 {name}'):
                dev.connect()
            actual = int(dev.videocapture.get(cv2.CAP_PROP_FOURCC))
            actual = ''.join(chr((actual >> (8 * i)) & 255) for i in range(4))
            require(not dev.config.fourcc or actual == dev.config.fourcc, f'FOURCC fallback: {actual}')
        start = time.monotonic()
        progress = Progress('双相机帧率检查', seconds, '秒')
        progress.update(0)
        while time.monotonic() - start < seconds:
            for name, dev in devices.items():
                dev.read_latest()  # Enforce the driver's stale-frame timeout.
                with dev.frame_lock:
                    frame, stamp = dev.latest_frame, dev.latest_timestamp
                if frame is not None and stamp != stamps[name]:
                    counts[name] += 1
                    stamps[name] = stamp
                    if preview:
                        rr.log(name, rr.Image(frame))
            time.sleep(.002)
            progress.update(min(int(time.monotonic() - start), seconds - 1))
        elapsed = time.monotonic() - start
        rates = {n: c / elapsed for n, c in counts.items()}
        for name, rate in rates.items():
            print(f'{name}: {rate:.1f} FPS, {counts[name]} unique timestamps / {elapsed:.1f}s')
            require(rate >= int(env('FPS')) * .9, f'{name} below 90% of target FPS.')
        progress.update(seconds)
        print('CAMERAS PASSED. Preview roles must still be confirmed by covering each lens separately.')
    finally:
        for dev in devices.values():
            if dev.is_connected:
                dev.disconnect()
        if preview:
            from lerobot.utils.visualization_utils import shutdown_visualization
            shutdown_visualization('rerun')


def hardware(with_cameras=True, require_calibration=True):
    require(importlib.metadata.version('lerobot') == '0.6.1', 'Activate LeRobot v0.6.1.')
    require(sys.version_info[:2] == (3, 12), 'Python 3.12 is required.')
    require(shutil.disk_usage(Path(env('FMS688_DATA'))).free >= float(env('MIN_FREE_GB')) * 1024**3,
            'Insufficient free space; keep at least MIN_FREE_GB, plus estimated session storage.')
    ports = [Path(env(x)) for x in ('FOLLOWER_PORT', 'LEADER_PORT')]
    require(ports[0].resolve() != ports[1].resolve(), 'Duplicate serial device.')
    for p in ports:
        require(p.is_char_device() and os.access(p, os.R_OK | os.W_OK), f'Port unavailable: {p}')
        props = subprocess.check_output(['udevadm', 'info', '-q', 'property', '-n', str(p)], text=True)
        require('1080P_USB_Camera' not in props, 'Camera auxiliary serial interface cannot control an arm.')
    base = Path(env('CALIBRATION_ROOT'))
    for relative, ident in [('robots/so_follower', 'FOLLOWER_ID'), ('teleoperators/so_leader', 'LEADER_ID')]:
        calibration_path = base / relative / (env(ident) + '.json')
        if not require_calibration and not calibration_path.exists():
            continue
        calibration = read_json(calibration_path)
        motors = {'shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'}
        require(set(calibration) == motors, f'Wrong calibration motors: {ident}')
        for motor, value in calibration.items():
            require(all(k in value for k in ('id', 'drive_mode', 'homing_offset', 'range_min', 'range_max')),
                    f'Incomplete calibration: {motor}')
            require(value['range_min'] < value['range_max'], f'Invalid calibration range: {motor}')
    if with_cameras:
        cameras()
    print('HARDWARE PREFLIGHT PASSED (no motor commands sent).')


def initialize_follower_goal():
    """Hold the follower at the intended start pose before teleop/record.

    SOFollower.connect() re-enables torque inside configure(). If Goal_Position is
    stale (observed 0 after power-up), that enable can drive the arm toward the
    stale goal before max_relative_target can clamp any action. With the operator
    holding the arm: keep torque off, write Goal_Position=Present_Position, verify
    the write, then explicitly enable torque so the arm holds the start pose.
    """
    require(sys.stdin.isatty(), 'Goal initialization requires an interactive terminal and onsite operator.')
    print('从臂启动前初始化：请托稳从臂，并与主臂摆到同一自然起始姿态，保持不动。')
    require(input('确认已托稳并对齐，输入 HOLD: ').strip() == 'HOLD', 'Goal initialization not confirmed.')

    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    calibration_dir = Path(env('CALIBRATION_ROOT')) / 'robots/so_follower'
    device = SO101Follower(SO101FollowerConfig(port=env('FOLLOWER_PORT'), id=env('FOLLOWER_ID'),
                                               calibration_dir=calibration_dir))
    bus = device.bus
    try:
        bus.connect()
        if any(bus.read('Torque_Enable', name, normalize=False) for name in bus.motors):
            bus.disable_torque()
            time.sleep(0.05)
        torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
        require(not any(torque.values()), f'Torque could not be disabled: {torque}')

        present = bus.sync_read('Present_Position', normalize=False)
        goal_before = {name: bus.read('Goal_Position', name, normalize=False) for name in bus.motors}
        print(f'Goal before: {goal_before}; present: {present}', flush=True)

        bus.sync_write('Goal_Position', present, normalize=False)
        time.sleep(0.1)
        goal_after = {name: bus.read('Goal_Position', name, normalize=False) for name in bus.motors}
        require(all(abs(goal_after[name] - present[name]) <= 2 for name in bus.motors),
                f'Goal_Position verification failed: {goal_after} vs {present}')

        bus.enable_torque()
        time.sleep(0.1)
        torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
        require(all(torque.values()), f'Torque enable failed: {torque}')
        present_after = bus.sync_read('Present_Position', normalize=False)
        require(all(abs(present_after[name] - present[name]) <= 10 for name in bus.motors),
                f'Arm moved during Goal initialization: {present_after} vs {present}')
        print('FOLLOWER GOAL INITIALIZED: Goal=Present, torque enabled, start pose held.', flush=True)
    except BaseException:
        try:
            if bus.is_connected:
                bus.disable_torque()
        except Exception as exc:
            print(f'WARNING: torque disable failed after Goal init error: {exc}; cut power.', file=sys.stderr)
        raise
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


def read_joint_bus(bus):
    """Open a bus and read registers only; never change torque or motor configuration."""
    try:
        bus.connect()
        positions = bus.sync_read('Present_Position', normalize=False)
        torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
        calibration = bus.read_calibration()
        return {name: {'id': motor.id, 'position_raw': positions[name], 'torque_enabled': torque[name],
                       'range_min': calibration[name].range_min, 'range_max': calibration[name].range_max,
                       'homing_offset': calibration[name].homing_offset}
                for name, motor in bus.motors.items()}
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


def compare_joint_calibration(snapshot, saved):
    require(set(snapshot) == set(saved), 'Motor names differ between readback and calibration file.')
    differences = []
    for joint, values in snapshot.items():
        for field in ('id', 'range_min', 'range_max', 'homing_offset'):
            actual, expected = values[field], getattr(saved[joint], field)
            if actual != expected:
                differences.append((joint, field, actual, expected))
    return differences


def calibrate_follower_torque_off(device):
    """Run the device calibration without its torque-enabling connect/configure path."""
    bus = device.bus
    try:
        bus.connect()
        torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
        require(all(value == 0 for value in torque.values()), f'Torque is not disabled: {torque}')
        require(bus.is_calibrated, 'Motor calibration changed since the saved file; stop and inspect.')
        device.calibrate()
        require(bus.is_calibrated, 'Written calibration does not match motor readback.')
        torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
        require(all(value == 0 for value in torque.values()), f'Torque unexpectedly enabled: {torque}')
        print('FOLLOWER CALIBRATION VERIFIED: motor ranges/offsets match file; torque readback is disabled.')
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


def guided_calibration(arm):
    require_physical_clearance()
    require(sys.stdin.isatty(), 'Calibration requires an interactive terminal and onsite operator.')
    require(arm in ('leader', 'follower'), 'Choose one arm at a time.')
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    base = Path(env('CALIBRATION_ROOT'))
    if arm == 'leader':
        folder, ident, port = base / 'teleoperators/so_leader', env('LEADER_ID'), env('LEADER_PORT')
        device = SO101Leader(SO101LeaderConfig(port=port, id=ident, calibration_dir=folder))
    else:
        folder, ident, port = base / 'robots/so_follower', env('FOLLOWER_ID'), env('FOLLOWER_PORT')
        device = SO101Follower(SO101FollowerConfig(port=port, id=ident, calibration_dir=folder))
    print('校准将写入舵机零偏和行程。先排除故障、托稳机械臂，释放力矩时可能下落。')
    require(input('确认现场安全且要校准，输入 CALIBRATE: ').strip() == 'CALIBRATE', 'Calibration not confirmed.')
    hardware(with_cameras=False, require_calibration=False)
    with lock():
        calibration = folder / (ident + '.json')
        if calibration.exists():
            backup = Path(env('FMS688_DATA')) / 'calibration-backups' / (arm + '-' + str(time.time_ns()) + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(calibration, backup)
            require(backup.read_bytes() == calibration.read_bytes(), 'Calibration backup verification failed.')
            print(f'原校准文件已备份: {backup}')
        bus = device.bus
        try:
            bus.connect()
            torque = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
            require(all(value == 0 for value in torque.values()), f'Torque must already be disabled: {torque}')
            print('如提示使用现有校准或重新校准，输入 c 再回车；按提示摆中位和记录行程。')
            print('腕部旋转 wrist_roll 不参与行程扫描；不要顶限位或强扳。')
            device.calibrate()
            require(bus.is_calibrated, 'Written calibration does not match motor readback.')
            print('校准文件与电机参数一致；仍须人工检查姿态与方向。')
        finally:
            if bus.is_connected:
                bus.disconnect(disable_torque=False)


def incident_calibrate_follower(backup):
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    hold = Path(env('FMS688_DATA')) / 'PHYSICAL_SAFETY_HOLD.md'
    require(hold.is_file(), 'Incident calibration requires the existing incident safety hold.')
    require(sys.stdin.isatty(), 'Incident calibration requires an interactive terminal.')
    current = Path(env('CALIBRATION_ROOT')) / 'robots/so_follower' / (env('FOLLOWER_ID') + '.json')
    require(backup and Path(backup).is_file(), 'A verified follower calibration backup is required.')
    require(hashlib.sha256(Path(backup).read_bytes()).digest() == hashlib.sha256(current.read_bytes()).digest(),
            'Backup does not match the current follower calibration; stop.')
    print('从臂事故保护仍生效；此校准会写入零偏、范围和文件，不启用跟随。')
    require(input('确认从臂已托稳、空载、现场可立即断电，输入 CALIBRATE: ').strip() == 'CALIBRATE',
            'Calibration not confirmed.')
    hardware(with_cameras=False)
    device = SO101Follower(SO101FollowerConfig(port=env('FOLLOWER_PORT'), id=env('FOLLOWER_ID'),
                          calibration_dir=current.parent))
    with lock():
        calibrate_follower_torque_off(device)


def inspect_joints(incident_read_only=False, arm='both'):
    """Read current registers without issuing any position, calibration, or torque writes."""
    if incident_read_only:
        authorize_incident_read()
    else:
        require_physical_clearance()
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    require(sys.stdin.isatty(), 'Joint inspection requires an interactive terminal and an onsite operator.')
    hardware(with_cameras=False)
    base = Path(env('CALIBRATION_ROOT'))
    devices = []
    if arm in ('leader', 'both'):
        devices.append(('leader', SO101Leader(SO101LeaderConfig(port=env('LEADER_PORT'), id=env('LEADER_ID'),
                       calibration_dir=base / 'teleoperators/so_leader'))))
    if arm in ('follower', 'both'):
        devices.append(('follower', SO101Follower(SO101FollowerConfig(port=env('FOLLOWER_PORT'), id=env('FOLLOWER_ID'),
                       calibration_dir=base / 'robots/so_follower'))))
    with lock():
        progress = Progress('只读关节检查', len(devices), '条机械臂')
        progress.update(0)
        for completed, (name, device) in enumerate(devices, 1):
            print(name + ':', flush=True)
            snapshot = read_joint_bus(device.bus)
            for joint, values in snapshot.items():
                print(f"  {joint} id={values['id']} position_raw={values['position_raw']} "
                      f"torque={values['torque_enabled']} range={values['range_min']}..{values['range_max']} "
                      f"offset={values['homing_offset']}")
            differences = compare_joint_calibration(snapshot, device.calibration)
            if differences:
                for joint, field, actual, expected in differences:
                    print(f'  校准差异 {joint} {field}: 读取或配置值={actual}, 文件={expected}')
            else:
                print('  已读范围和偏移与文件一致；不代表实际机械姿态或方向正确。')
            progress.update(completed)
    print('Read-only snapshot; torque state was not changed. Values alone do not prove physical alignment or safety.')


def run_record(command):
    require_physical_clearance()
    writable()
    require(sys.stdin.isatty(), 'Recording requires a local interactive terminal.')
    with lock():
        state = session()
        require(state['status'] != 'closed', 'Round already closed.')
        total = count()
        if root().exists():
            validate(allow_empty=env('ROUND_ID') == 'r01' and state['start_episode'] == 0)
        saved = total - state['start_episode']
        remaining = state['target_episodes'] - saved
        require(0 <= saved and remaining > 0, 'Round complete or inconsistent; review it instead of recording.')
        hardware()
        initialize_follower_goal()
        command = [x for x in command if not x.startswith(('--dataset.num_episodes=', '--resume='))]
        if not any(x.startswith('--robot.max_relative_target=') for x in command):
            command.append(f'--robot.max_relative_target={os.environ.get("MAX_RELATIVE_TARGET", "1.0")}')
        command.append(f'--dataset.num_episodes={remaining}')
        if root().exists():
            command.append('--resume=true')
        state.update(status='recording', started_at=now())
        write_json(round_dir() / 'SESSION.json', state)
        print(f'RECORD: saved={saved}, remaining={remaining}; n=next, r=discard/re-record, q=finish current buffer and quit.', flush=True)
        print('Reset still teleoperates. Time limits advance automatically. q is NOT emergency stop.', flush=True)
        code = 1
        try:
            code = subprocess.call(command)
        finally:
            state.update(status='needs_review', last_exit=code, stopped_at=now())
            try:
                state['saved_episodes'] = count() - state['start_episode']
                if 0 <= state['saved_episodes'] <= state['target_episodes']:
                    Progress('本组已保存', state['target_episodes'], '条').update(state['saved_episodes'])
                print('录制已结束；保存结果仍需检查与审核。', flush=True)
            except Exception as exc:
                state['status'] = 'needs_recovery'
                state['error'] = str(exc)
            write_json(round_dir() / 'SESSION.json', state)
        if code != 0 and state['status'] == 'needs_review' and state['start_episode'] == 0 and state['saved_episodes'] == 0:
            raise RuntimeError(f'Recording exited {code}; no episodes saved. Preserve data; after resolving the error, '
                               'resume only if the empty dataset check passes.')
        require(code == 0, f'Recording exited {code}; preserve data and run review before resuming.')


def review():
    with lock():
        state = session()
        validate()
        total = count()
        require(state['start_episode'] <= total <= state['start_episode'] + state['target_episodes'], 'Round episode range mismatch.')
        report = round_dir() / 'QA.csv'
        existing = {}
        if report.exists():
            with report.open(newline='') as stream:
                existing = {int(row['episode']): row for row in csv.DictReader(stream)}
        old = round_dir() / 'VALIDATION.json'
        files = snapshot()
        if old.exists() and read_json(old)['files'] != files:
            existing = {}  # changed data must be reviewed again
        with report.open('w', newline='') as stream:
            fields = ['episode', 'item', 'result', 'privacy', 'notes']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for ep in range(state['start_episode'], total):
                writer.writerow(existing.get(ep, {'episode': ep, 'result': 'pending', 'privacy': 'pending'}))
        write_json(old, {'at': now(), 'total_episodes': total, 'files': files})
        print(f'Inspect every episode with view --episode N, then fill {report}: result=pass, privacy=pass, item and notes.')


def close_round():
    with lock():
        state = session()
        total = count()
        require(total == state['start_episode'] + state['target_episodes'], 'Round has not reached its target.')
        require(read_json(round_dir() / 'VALIDATION.json')['files'] == snapshot(), 'Dataset changed; run review again.')
        with (round_dir() / 'QA.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        require(len(rows) == state['target_episodes'], 'Wrong QA row count.')
        require({int(r['episode']) for r in rows} == set(range(state['start_episode'], total)), 'QA episode mismatch.')
        require(all(r['result'] == 'pass' and r['privacy'] == 'pass' and r['item'].strip() for r in rows),
                'All episodes need human result=pass, privacy=pass and item.')
        state.update(status='closed', saved_episodes=state['target_episodes'], closed_at=now())
        write_json(round_dir() / 'SESSION.json', state)
        with (round_dir() / 'ROUND.md').open('a') as stream:
            stream.write(f'quality=pass\nstatus=closed\nclosed_at={now()}\n')
        print('ROUND CLOSED: local quality and public-release review recorded.')


def upload(api=None):
    from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
    from lerobot.datasets.dataset_metadata import CODEBASE_VERSION
    require(not Path(env('DATASET_QUARANTINE')).exists(), 'Dataset quarantined.')
    with lock():
        state = session()
        require(state['status'] == 'closed', 'Close the round before uploading.')
        all_states = [read_json(p) for p in round_dir().parent.glob('r*/SESSION.json')]
        require(all(s['status'] == 'closed' for s in all_states), 'All rounds must be closed.')
        files = snapshot()
        require(read_json(round_dir() / 'VALIDATION.json')['files'] == files, 'Data changed after review; review again.')
        api = api or HfApi()
        require(api.whoami()['name'] == 'fms688', 'Log in with hf auth login as fms688.')
        repo = env('DATASET_ID')
        require(repo == 'fms688/arm101_desktop_collection', 'This public uploader is restricted to the approved repository.')
        remote = api.dataset_info(repo)
        require(not remote.private, 'Expected the approved public repository; do not change visibility automatically.')
        existing = {s.rfilename for s in remote.siblings}
        identity = {'repo_id': repo, 'task': env('TASK_SLUG'), 'description': env('TASK_DESCRIPTION'),
                    'version': env('DATASET_VERSION'), 'fingerprint': state['fingerprint']}
        dataset_prefixes = ('meta/', 'data/', 'images/', 'videos/')
        if any(p.startswith(dataset_prefixes) for p in existing):
            require('COLLECTION_IDENTITY.json' in existing, 'Existing remote data has no verified project identity; reconcile manually.')
            old_identity = read_json(hf_hub_download(repo_id=repo, filename='COLLECTION_IDENTITY.json', repo_type='dataset', revision=remote.sha))
            require(old_identity == identity, 'Remote task/version/hardware differs; never mix datasets.')
            remote_info = read_json(hf_hub_download(repo_id=repo, filename='meta/info.json', repo_type='dataset', revision=remote.sha))
            require(remote_info['total_episodes'] <= count(), 'Remote dataset is newer/larger than local data.')
            require(all(remote_info['features'].get('observation.images.' + camera, {}).get('dtype') == 'image'
                        for camera in ('top', 'wrist')), 'Remote camera format differs; never mix video and images.')
        require(not {p for p in existing if p.startswith(dataset_prefixes)} - set(files),
                'Remote has extra dataset files. Stop to reconcile; never silently mix versions.')
        tags_before = {t.name: t.target_commit for t in api.list_repo_refs(repo, repo_type='dataset').tags}
        with tempfile.TemporaryDirectory(prefix='so101-upload-') as tmp:
            # Preserve the repository owner\'s card; add a separate task description.
            description = Path(tmp) / 'COLLECTION.md'
            description.write_text(f'# SO101 desktop collection\n\nTask: {env("TASK_DESCRIPTION")}\n\n'
                f'Version: {env("DATASET_VERSION")}; cameras: top and wrist; FPS: {env("FPS")}.\n'
                f'Episodes: {count()}. Human quality and public-release review completed.\n')
            operations = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=str(root() / p)) for p in files]
            operations.append(CommitOperationAdd(path_in_repo='COLLECTION.md', path_or_fileobj=str(description)))
            operations.append(CommitOperationAdd(path_in_repo='COLLECTION_IDENTITY.json',
                              path_or_fileobj=json.dumps(identity, ensure_ascii=False).encode()))
            with waiting('上传数据及等待服务器提交'):
                result = api.create_commit(repo_id=repo, repo_type='dataset', operations=operations,
                    commit_message=f'Upload reviewed {env("ROUND_ID")} {env("DATASET_VERSION")}', parent_commit=remote.sha)
        # Only claim success after remote metadata and file sizes match the pinned commit.
        confirmed = api.dataset_info(repo, revision=result.oid, files_metadata=True)
        sizes = {s.rfilename: s.size for s in confirmed.siblings}
        require(all(sizes.get(p) == (root() / p).stat().st_size for p in files), 'Remote size verification failed; retry upload.')
        require(snapshot() == files, 'Local data changed during upload; no successful receipt recorded.')
        # Default LeRobot Hub readers resolve CODEBASE_VERSION rather than main.
        # Match LeRobot's own publisher while guarding concurrent tag changes.
        tags_now = {t.name: t.target_commit for t in api.list_repo_refs(repo, repo_type='dataset').tags}
        require(tags_now.get(CODEBASE_VERSION) == tags_before.get(CODEBASE_VERSION), 'Remote version tag changed concurrently; retry after checking it.')
        require(api.dataset_info(repo).sha == result.oid, 'Remote main changed after upload; stop before updating the version tag.')
        if tags_now.get(CODEBASE_VERSION) != result.oid:
            if CODEBASE_VERSION in tags_now:
                api.delete_tag(repo, tag=CODEBASE_VERSION, repo_type='dataset')
            api.create_tag(repo, tag=CODEBASE_VERSION, revision=result.oid, repo_type='dataset')
        require(api.dataset_info(repo, revision=CODEBASE_VERSION).sha == result.oid, 'Version tag verification failed; retry upload.')
        write_json(round_dir() / 'UPLOAD.json', {'repo_id': repo, 'commit': result.oid, 'at': now(), 'files': files,
            'format_tag': CODEBASE_VERSION, 'browser_verified': False, 'url': f'https://huggingface.co/datasets/{repo}'})
        print(f'UPLOAD VERIFIED: {result.oid}')
        print(f'https://huggingface.co/spaces/lerobot/visualize_dataset (enter {repo})')
        print('Browser playback remains a separate manual acceptance step.')


def teleop(with_cameras, confirm, diagnose_joint3=False):
    args = ['lerobot-teleoperate', '--robot.type=so101_follower', f'--robot.port={env("FOLLOWER_PORT")}',
            f'--robot.id={env("FOLLOWER_ID")}', '--teleop.type=so101_leader', f'--teleop.port={env("LEADER_PORT")}',
            f'--teleop.id={env("LEADER_ID")}', f'--fps={env("FPS")}',
            f'--robot.calibration_dir={env("CALIBRATION_ROOT")}/robots/so_follower',
            f'--robot.max_relative_target={os.environ.get("MAX_RELATIVE_TARGET", "1.0")}',
            f'--teleop.calibration_dir={env("CALIBRATION_ROOT")}/teleoperators/so_leader']
    if with_cameras:
        configs = {n: {'type': 'opencv', 'index_or_path': str(c.index_or_path), 'width': c.width,
                      'height': c.height, 'fps': c.fps, 'fourcc': c.fourcc} for n, c in camera_configs().items()}
        args += ['--robot.cameras=' + json.dumps(configs), '--display_data=true']
    if diagnose_joint3:
        args = [sys.executable, str(Path(__file__).with_name('joint3_monitor.py'))] + args[1:]
        args.append('--teleop_time_s=10')
    import shlex
    print(shlex.join(args), flush=True)
    if confirm:
        require_physical_clearance()
        require(sys.stdin.isatty(), 'Teleoperation requires an interactive terminal.')
        with lock():
            hardware(with_cameras)
            initialize_follower_goal()
            if diagnose_joint3:
                log_dir = Path(env('FMS688_DATA')) / 'logs'
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / f'joint3-diagnostic-{time.time_ns()}.csv'
                print(f'JOINT3 LOG: {log_path}', flush=True)
                subprocess.run(args, check=True, env={**os.environ, 'SO101_JOINT3_LOG': str(log_path)})
            else:
                with waiting('实时跟随；按 Ctrl+C 停止'):
                    subprocess.run(args, check=True)
    else:
        print('Dry-run. Use --confirm-physical only after workstation and stop/power checks.')


def main():
    parser = argparse.ArgumentParser(description='SO101 collection stages (use collect.sh to load config)')
    parser.add_argument('stage', choices=['doctor', 'devices', 'cameras', 'teleop', 'diagnose-joint3', 'inspect-joints', 'calibrate-arm', 'incident-calibrate-follower', 'init', 'run', 'review', 'view', 'close', 'upload', 'hardware'])
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--with-cameras', action='store_true')
    parser.add_argument('--confirm-physical', action='store_true')
    parser.add_argument('--incident-read-only', action='store_true')
    parser.add_argument('--arm', choices=['leader', 'follower', 'both'], default='both')
    parser.add_argument('--calibration-backup')
    parser.add_argument('--confirm-public', action='store_true')
    parser.add_argument('--episode', type=int, default=0)
    # run passes the exact command array after --, never a shell string.
    raw = sys.argv[1:]
    command = raw[raw.index('--') + 1:] if '--' in raw else []
    opts = parser.parse_args(raw[:raw.index('--')] if '--' in raw else raw)
    require(not opts.incident_read_only or opts.stage == 'inspect-joints',
            '--incident-read-only applies only to read-only joint inspection.')
    if opts.stage == 'doctor':
        print('Python:', sys.version.split()[0], 'environment:', sys.prefix)
        for n in ['lerobot', 'torch', 'torchvision', 'torchcodec', 'numpy', 'huggingface-hub']:
            print(n, importlib.metadata.version(n))
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
        print('Free GB:', round(shutil.disk_usage(env('FMS688_DATA')).free / 1024**3, 1))
        subprocess.run(['hf', 'auth', 'whoami'], check=True)
    elif opts.stage == 'devices':
        subprocess.run(['v4l2-ctl', '--list-devices'], check=True)
        for directory in ('/dev/serial/by-id', '/dev/v4l/by-id'):
            for path in sorted(Path(directory).glob('*')):
                print(path, '->', path.resolve())
        print('Built-in FHD Camera excluded. Match each external device by unplug/replug and lens covering.')
    elif opts.stage == 'cameras':
        require(10 <= opts.seconds <= 600, 'Choose 10..600 seconds.')
        cameras(opts.seconds, preview=True)
    elif opts.stage == 'teleop':
        teleop(opts.with_cameras, opts.confirm_physical)
    elif opts.stage == 'diagnose-joint3':
        require(opts.confirm_physical, 'Joint 3 diagnosis needs --confirm-physical and onsite supervision.')
        teleop(False, True, diagnose_joint3=True)
    elif opts.stage == 'inspect-joints':
        require(opts.confirm_physical, 'Joint inspection needs --confirm-physical and onsite supervision; powering motors may cause movement.')
        inspect_joints(incident_read_only=opts.incident_read_only, arm=opts.arm)
    elif opts.stage == 'calibrate-arm':
        require(opts.confirm_physical, 'Calibration needs --confirm-physical and onsite supervision.')
        guided_calibration(opts.arm)
    elif opts.stage == 'incident-calibrate-follower':
        require(opts.confirm_physical, 'Incident calibration needs --confirm-physical and onsite supervision.')
        incident_calibrate_follower(opts.calibration_backup)
    elif opts.stage == 'hardware':
        hardware()
    elif opts.stage == 'init':
        with lock():
            init()
    elif opts.stage == 'run':
        run_record(command)
    elif opts.stage == 'review':
        review()
    elif opts.stage == 'close':
        close_round()
    elif opts.stage == 'view':
        with waiting('数据回放窗口，关闭窗口后返回菜单'):
            subprocess.run(['lerobot-dataset-viz', '--repo-id', env('DATASET_ID'), '--root', str(root()),
                            '--mode', 'local', '--episode-index', str(opts.episode)], check=True)
    elif opts.stage == 'upload':
        require(opts.confirm_public, 'Public upload needs --confirm-public after QA and privacy review.')
        upload()


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'ERROR: {exc or "Interrupted; preserve data and review before resuming."}', file=sys.stderr)
        sys.exit(1)
