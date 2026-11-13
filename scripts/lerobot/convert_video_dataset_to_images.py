"""Copy a LeRobot v3 video dataset into a separate image-feature dataset.

Run in the collector's LeRobot environment, where PyAV can decode the source.
The source is only read; the destination must not exist yet.
"""

import argparse
from copy import deepcopy
from pathlib import Path

import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.utils.constants import DEFAULT_FEATURES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-repo-id", required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve(strict=True)
    output_root = args.output_root.resolve(strict=False)
    if not (source_root / "meta/info.json").is_file():
        parser.error("source is missing meta/info.json")
    if output_root.exists():
        parser.error("output directory already exists; choose a new path")
    if output_root == source_root or source_root in output_root.parents:
        parser.error("output must be outside the source dataset")
    if args.repo_id == args.output_repo_id:
        parser.error("output repo id must differ from source repo id")

    source = LeRobotDataset(args.repo_id, root=source_root, video_backend="pyav")
    if not source.meta.video_keys or source.meta.image_keys:
        parser.error("expected video features only; inspect this dataset before converting")
    if not len(source) or not source.num_episodes:
        parser.error("source dataset is empty")

    features = deepcopy({key: value for key, value in source.features.items() if key not in DEFAULT_FEATURES})
    for key in source.meta.video_keys:
        features[key]["dtype"] = "image"

    output_root.parent.mkdir(parents=True, exist_ok=True)
    output = LeRobotDataset.create(
        args.output_repo_id,
        fps=source.fps,
        features=features,
        root=output_root,
        robot_type=source.meta.robot_type,
        use_videos=False,
    )
    previous_episode = None
    completed_episodes = 0
    for index in range(len(source)):
        item = source[index]
        episode = int(item["episode_index"])
        if previous_episode is not None and episode != previous_episode:
            output.save_episode()
            completed_episodes += 1
        frame = {key: item[key] for key in features}
        for key in source.meta.video_keys:
            chw = np.asarray(frame[key])
            frame[key] = np.clip(chw.transpose(1, 2, 0) * 255, 0, 255).astype(np.uint8)
        frame["task"] = item["task"]
        output.add_frame(frame)
        previous_episode = episode
    output.save_episode()
    output.finalize()
    completed_episodes += 1

    converted = LeRobotDataset(args.output_repo_id, root=output_root)
    if len(converted) != len(source) or converted.num_episodes != source.num_episodes:
        raise RuntimeError("converted frame/episode count differs from source")
    if converted.meta.video_keys or set(converted.meta.image_keys) != set(source.meta.video_keys):
        raise RuntimeError("converted camera features differ from source")
    print(f"CONVERTED: {len(converted)} frames, {completed_episodes} episodes, {sorted(converted.meta.image_keys)}")
    print(f"Output: {output_root}")


if __name__ == "__main__":
    main()
