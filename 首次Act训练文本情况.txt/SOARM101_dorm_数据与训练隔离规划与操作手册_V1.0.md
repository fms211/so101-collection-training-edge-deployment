# SOarm101_dorm 数据与训练隔离规划与操作手册 V1.0

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.0 |
| 日期 | 2026-09-24 |
| 工作区名 | `soarm101_dorm` |
| 机器人 | SOarm101（SO-101 单臂，6 电机） |
| 策略模型 | ACT（Action Chunking Transformer），LeRobot 0.6.2 实现 |
| 训练服务器 | 4×RTX 5090，conda 环境 `station_act`（老师预配，只复用不修改） |
| 数据来源 | 宿舍 SOarm101 采集 → 传到本服务器训练/推理 |

---

## 1. 本手册怎么用（10 分钟导读）

**你的三条主线：**

1. **数据怎么进来**：宿舍采集 → `rsync` 传到服务器隔离区 `data/raw_inbox/`（第 8 章）；
2. **数据放哪**：隔离区校验 → 放行到 `data/raw/` →（路线②转换）→ 训练就绪区 `data/lerobot/soarm101_dorm_act_v1/`（第 3、5–7 章）；
3. **怎么开训**：数据就位后跑 `scripts/train/train_soarm101_dorm_act_v1.sh`，权重落到 `outputs/`（第 10 章）。

**硬规则一页速查**（详见第 11 章红线）：

| # | 红线 | 一句话原因 |
|---|---|---|
| 1 | 禁止 video 特征 / `--use-videos` | 服务器 torchcodec 损坏，视频读不了 |
| 2 | 不动 `lumousTest/lin/src/lerobot` 的 git 状态 | 全服务器 lerobot 都指向它（editable） |
| 3 | 不修改 7 个 station 脚本本体 | 双臂 14 维写死，且是老师实验的可追溯资产 |
| 4 | 不新建 conda env、不重装 lerobot | 环境是冻结基线 |
| 5 | 一切产物写进 `soarm101_dorm/` 内 | 数据/训练隔离 |
| 6 | 数据必经 `raw_inbox → raw`，禁止跳过校验 | 防脏数据污染 |

**推荐阅读顺序**：第 2 章（现状）→ 第 3 章（目录）→ 第 4 章（放哪）→ 第 5/6/7 章（按你的采集格式二选一）→ 第 8 章（传输）→ 第 10 章（训练）。

---

## 2. 服务器现状梳理

### 2.1 磁盘

| 挂载点 | 总量 | 已用 | 可用 | 用途判断 |
|--------|------|------|------|----------|
| `/`（/dev/sda2） | 439G | 161G | **256G** | 系统 + 全部现有训练数据（**默认放这**） |
| `/mnt`（/dev/nvme0n1p1） | 1.8T | 8.8G | **1.7T** | 几乎全空，大数据集/归档备选（第 13 章） |
| `/media/server/KINGSTON` | 116G | 45G | 72G | U 盘，只作冷备 |

### 2.2 `/home/server/` 顶层格局

| 路径 | 大小 | 类型 | 说明 |
|------|------|------|------|
| **`lumousTest/`** | **72G** | **训练主工作区（老师实验沙盒）** | 只读引用，见 2.3 |
| `miniconda3/` | 15G | Conda 安装 | 环境见 2.4 |
| `openpi-edu/` | 空 | 预留 | 与本项目无关 |
| `.cache/` | 53G | 缓存 | huggingface 46G、pip 6.6G |
| `soarm101_dorm/` | <1M | **本工作区（你的）** | 本文档所在处 |
| 其他 | — | 系统/工具 | 下载、备份压缩包、syncthing 等，与训练无关 |

另：`/home/lin/src/lerobot` 是另一份 LeRobot 源码检出（root 属主），与我们无关；`/home/lumos/` 不存在。

### 2.3 `lumousTest/` —— 现有训练主文件夹与数据文件夹层级

```
/home/server/lumousTest/                          72G  现有训练主工作区
├── CLAUDE.md                                          工作区说明（管线/硬规则/命令）
├── lin/src/lerobot/                              30M  ★ 代码文件夹：LeRobot 0.6.2 源码
│                                                      pinned commit 3f2c29ef7e44b1ddccbcda3b6a63939e53639e9e
│                                                      （station_act 环境的 lerobot 为 editable 指向这里，绝不能动）
├── 20260914/                                     ~31G  Station Lite 双臂实验（唯一活跃实验）
│   ├── task_put_in_pen_container/               3.8G  ★ 数据文件夹（raw）：45 个 episode，
│   │                                                      每条 data.json + colors/*.jpg（head/left_wrist/right_wrist 三相机）
│   ├── act_intermediate_train_class/            3.7G  ★ 数据文件夹（中间格式）：45-episode
│   ├── act_intermediate_smoke_class/             59M  ★ 数据文件夹（中间格式）：1-episode 冒烟
│   ├── lerobot_station_lite_train_class/         23G  ★ 数据文件夹（LeRobot v3 训练集）：data/ images/ meta/
│   ├── lerobot_smoke_class/                     364M  ★ 数据文件夹（LeRobot v3 冒烟集）
│   ├── outputs/act_station_lite_class/          2.4G  ★ 训练产物：checkpoints/{002000..008000,last}/pretrained_model/
│   ├── scripts/                                  80K  ★ 代码文件夹（canonical）：7 个管线脚本
│   ├── station_act_training_kit/                 96K  scripts/ 的 byte-identical 打包副本 + README
│   ├── episode_manifest_*.json                            crop 裁剪清单（3 个）
│   └── act_station_lite_class.log                434K  训练日志
└── other/                                         40G  参考资料
    ├── id_49_2026-08-31.tar.xz                   41G  原始采集大归档（勿动）
    ├── requirements.txt                         1.9K  ★ 冻结依赖清单（pip freeze，只读参考）
    ├── deepseek_bash_20260924_6a9d27.sh          819B  ★ 训练命令范本（本工作区 train 脚本即抄自它）
    ├── Station_Lite_ACT_5090_培训全流程手册_V1.0.pdf 等   中文培训/排障/部署文档
    └── scripts/、station_act_training_kit/                又两份脚本重复副本
```

**7 个 station 管线脚本**（`20260914/scripts/`，与副本 byte-identical）：

| 脚本 | 用途 | 对 SO-101 可否复用 |
|---|---|---|
| `station_episode_check.py` | raw 质检 | ✗ 写死三相机/双臂字段 |
| `build_training_manifest.py` | crop 清单 | ✗ 写死 22 个 Station episode 名 |
| `prepare_act_intermediate.py` | raw → 中间格式 | ✗ 写死 14 维双臂布局 |
| `convert_intermediate_to_lerobot.py` | 中间 → LeRobot | ✗ 写死 14 维/三相机；**骨架可抄**（第 7 章） |
| `station_act_offline_eval.py` | 开环离线评估 | ✗ 写死 14 维 |
| `station_act_http_server.py` | HTTP 推理服务 | ✗ 写死 14 维（要做 6 维变体，第 12 章） |
| `station_act_http_replay_client.py` | 回放观测客户端 | ✗ 写死 14 维/三相机 |

> **为什么不能直接复用**：这 7 个脚本的 state/action 是 Station Lite 双臂 **14 维**（左臂 7 + 右臂 7 / 左关节 6+爪 + 右关节 6+爪），相机固定 `cam_high/cam_left_wrist/cam_right_wrist` 三路，gripper 常量是 Station Lite 硬件标定值。SOarm101 是**单臂 6 电机**，直接跑必然报维度/键名错误。详见第 7 章。

### 2.4 Conda 环境（只复用 `station_act`）

| 环境 | Python | 用途 |
|------|--------|------|
| **`station_act`** ★ | 3.12.14 | **唯一训练环境**：lerobot 0.6.2（editable → `lumousTest/lin/src/lerobot`）、torch 2.11.0+cu130、accelerate 1.15.0、datasets 4.8.5 |
| `lerobot` | 3.11.16 | 仅 torch+cu128，**没有 lerobot 包，不能训练，勿用** |
| `base` | 3.14.7 | conda 管理入口，无训练包 |

- GPU：**4×RTX 5090，CUDA 可用**。
- 19 个 lerobot CLI 齐全：`lerobot-train / eval / record / replay / teleoperate / calibrate / find-port / setup-motors / ...`（均在 `/home/server/miniconda3/envs/station_act/bin/`）。
- **已知故障：torchcodec 损坏**（libstdc++ CXXABI 缺口）→ 一切 **video 解码/`--use-videos` 不可用**；**图像特征数据集完全正常**。本工作区全链路强制图像特征。
- 冻结基线清单：`/home/server/lumousTest/other/requirements.txt`（**只读参考，不要按它重装**）。

### 2.5 ACT 策略代码位置

`/home/server/lumousTest/lin/src/lerobot/src/lerobot/policies/act/`：

- `configuration_act.py` — ACT 配置（`chunk_size`、`n_action_steps` 等）
- `modeling_act.py` — ACT 网络与推理/训练逻辑
- `processor_act.py` — 归一化等前后处理

**关键事实**：ACT 的输入/输出维度**从数据集元数据自动推断**（`dataset_to_policy_features`），不绑定 14 维或特定相机名 → **SO-101 的 6 维单臂数据可以直接用 `lerobot-train --policy.type=act` 训练**，这是"无缝衔接"的根基。SO-101 官方端到端流程见 `lin/src/lerobot/AGENT_GUIDE.md` §4。

---

## 3. 两类主文件夹层级说明（本工作区 `soarm101_dorm/`）

设计原则：**数据隔离 + 训练隔离**。你的数据、脚本、权重、日志全部只在 `soarm101_dorm/` 内；从宿舍传来的数据先落**隔离区**，校验后才放行，防止脏数据污染训练区。

### 3.1 完整目录树（每目录一句话用途）

```
soarm101_dorm/                                # ROOT 工作区根
├── README.md                                 # 入口指针
├── docs/                                     # 全部说明文档
│   └── SOARM101_dorm_数据与训练隔离规划与操作手册_V1.0.md  # 本文档
├── data/                                     # ★ 唯一数据区（数据隔离），一切数据不放 ROOT 外
│   ├── raw_inbox/                            # ★ 隔离区：宿舍传来先落这，未校验禁止训练
│   │   ├── route1_lerobot/                   #   路线①：LeRobot 数据集暂存（未校验）
│   │   └── route2_custom/                    #   路线②：自定义 raw 暂存（未校验）
│   ├── raw/                                  # 已校验原始数据（inbox 放行后，视为只读）
│   │   ├── route1_lerobot/                   #   ① 校验通过的 LeRobotDataset 原样保全
│   │   └── route2_custom/                    #   ② 校验通过的 raw episodes
│   ├── intermediate/route2_act/              # ② 专用中间格式（① 不用，保留空目录统一骨架）
│   └── lerobot/                              # 训练就绪 LeRobotDataset 的父目录
│       └── soarm101_dorm_act_v1/             #   ★ 具体数据集（训练时 --dataset.root 指向它）
│                                              #   注意：此目录不预建！由转换/移入生成（exist_ok=False）
├── scripts/                                  # ★ 本工作区私有脚本（训练隔离），绝不改 lumousTest 内脚本
│   ├── README.md                             # 各脚本服务哪条路线、输入输出
│   ├── convert/                              # 路线②转换脚本预留（格式确认后新写）
│   ├── train/
│   │   └── train_soarm101_dorm_act_v1.sh     # ★ 训练启动脚本（两路线共用，已就绪）
│   └── eval/README.md                        # 评估脚本预留
├── outputs/                                  # ★ 训练输出唯一目录
│   └── soarm101_dorm_act_v1/                 # --output_dir
│       └── checkpoints/                      # {0002000… last}/pretrained_model/ 权重
├── logs/                                     # 全部日志
│   ├── transfer/                             # rsync/校验日志
│   ├── convert/                              # ② 转换日志
│   └── train/                                # 训练 tee 日志
├── reports/                                  # 人读报告
│   ├── transfer/                             # 传输清单、校验报告
│   ├── train/                                # 训练摘要、失败分析
│   └── handover/                             # 交接/阶段小结
└── inference/                                # 推理部署预留（第 12 章）
    ├── server/                               # HTTP/推理服务预留（6 维变体）
    ├── client/                               # 客户端预留
    └── README.md                             # 说明 station HTTP 脚本为何不可复用
```

### 3.2 数据生命周期状态机（隔离规则的落地）

```
宿舍采集
   │  rsync（第 8 章）
   ▼
data/raw_inbox/{route1_lerobot|route2_custom}/batch_xxx/     【隔离区，未校验】
   │  校验通过（第 6/7 章校验清单）→ 出传输/校验报告到 reports/transfer/
   ▼
data/raw/{route1_lerobot|route2_custom}/batch_xxx/          【已校验，只读】
   │  路线①：mv 就位          路线②：转换脚本（scripts/convert/）
   ▼
data/lerobot/soarm101_dorm_act_v1/                          【训练就绪】
   │  bash scripts/train/train_soarm101_dorm_act_v1.sh（第 10 章）
   ▼
outputs/soarm101_dorm_act_v1/checkpoints/                   【训练产物】
```

- **禁止跳过校验**：校验失败的数据留在 `raw_inbox/` 并写报告，不得进 `raw/` 或 `lerobot/`。
- **route1_lerobot / route2_custom 约定**：`route1` = LeRobot 官方格式（原生数据集）；`route2` = 自定义 raw（如 data.json+jpg）。两条路线只在 `data/raw_inbox`、`data/raw`、`data/intermediate`、`scripts/convert` 分岔；`scripts/train`、`outputs`、`logs/train`、`data/lerobot/<repo_id>` **共用**。

---

## 4. 目录放哪：方案 A / 方案 B 对比与推荐

> 你的要求：两种位置都考虑、说清差异。**两方案的目录树与命令体完全相同，只差 `ROOT=` 一行。**

| | **方案 A：`/home/server/soarm101_dorm/`（★ 推荐，已按此创建）** | **方案 B：`/home/server/lumousTest/soarm101_dorm/`** |
|---|---|---|
| 位置 | `/home/server/` 顶层，与 `lumousTest` **平行** | 挂在老师实验沙盒 `lumousTest/` **内部** |
| 隔离边界 | 与老师的 72G 实验树**物理分离**，"我的文件"一眼可见，误 `rm`/误改面最小 | 与 raw 数据、脚本副本同根，容易误碰老师资产 |
| 交接/回收 | 拷走/删掉一个顶层目录即完成交接 | 需要从沙盒里小心摘子树 |
| 老师总览 | 稍分散（两个顶层目录） | 所有实验统一收在 `lumousTest/` 内，方便统一管理 |
| 与 pinned 资产的距离 | 隔一层，心理与操作上都更安全 | 与 `lin/src/lerobot`（editable 装载点）同树，风险感知弱 |
| 磁盘 | 同为 `/` 盘（余 256G），无差别 | 同左 |
| 命令差异 | `ROOT=/home/server/soarm101_dorm` | `ROOT=/home/server/lumousTest/soarm101_dorm` |

**推荐方案 A 的理由**：本项目核心诉求是"**与服务器上其他机械臂数据严格隔离、不影响现有基础环境和其他项目**"。方案 A 的物理边界最清晰——老师沙盒 `lumousTest/` 整树视为只读，你的东西全在自己顶层目录里，交接回收最简单。

**若老师/助教要求统一收在沙盒内（选方案 B）**：树与命令照旧，只改 `ROOT=`；并把下面一句贴在手册最顶上：

> ⚠️ `ROOT`（soarm101_dorm/）之外的 `lumousTest/**` 一律只读。不得写入、修改、删除其中任何文件。

**迁移方法**（A↔B 互换）：`mv /home/server/soarm101_dorm /home/server/lumousTest/soarm101_dorm`，再把 train 脚本里的 `ROOT=` 改掉即可。

---

## 5. 两条数据路线总览与选型

> 你的宿舍采集工具待确认（回宿舍看），故两条路线都给全步骤。**最终都汇入 `data/lerobot/soarm101_dorm_act_v1/` 后开训。**

| | **路线①：LeRobot 官方 so101 流程** | **路线②：自定义 raw（data.json + 图片）** |
|---|---|---|
| 宿舍用什么采 | `lerobot-record`（so101_follower + so101_leader） | 自家采集 App/上位机（类 Station Lite 形态） |
| 传上来是什么 | **LeRobotDataset**（meta/ data/ images/） | 每集一个目录：标注文件 + 相机图片 |
| 服务器上要转换吗 | **不用，零转换直训** | 要：新写 2 支转换脚本（第 7 章） |
| 数据落点 | `raw_inbox/route1_lerobot/` | `raw_inbox/route2_custom/` |
| 额外工作 | 宿舍装 LeRobot+Feetech 栈；录制**必须 `--dataset.video=false`** | 需先确认 raw 的字段 schema |

```
路线①: 宿舍 lerobot-record ──rsync──▶ raw_inbox/route1 ──校验──▶ raw/route1 ──mv──▶ data/lerobot/soarm101_dorm_act_v1 ─┐
                                                                                                                      ├─▶ 训练
路线②: 宿舍自定义 raw    ──rsync──▶ raw_inbox/route2 ──校验──▶ raw/route2 ──新写转换──▶ data/lerobot/soarm101_dorm_act_v1 ─┘
```

**选型建议**：若宿舍还没定采集工具、且可以选 → **优先路线①**（官方 `lerobot-record`），服务器侧零转换、格式自带归一化统计，最不容易出错。

---

## 6. 路线① 落地步骤（LeRobot 官方 so101 格式）

### 6.1 宿舍端采集（SO-101 官方流程，详见 `lin/src/lerobot/AGENT_GUIDE.md` §4）

```bash
# 一次性：找串口 / 设电机 ID / 标定
lerobot-find-port
lerobot-setup-motors --robot.type=so101_follower
lerobot-setup-motors --teleop.type=so101_leader
lerobot-calibrate --robot.type=so101_follower --robot.id=my_follower
lerobot-calibrate --teleop.type=so101_leader    --robot.id=my_leader

# 每次采集前：遥操检查（不录制）
lerobot-teleoperate --robot.type=so101_follower --robot.id=my_follower \
  --teleop.type=so101_leader --teleop.id=my_leader
```

### 6.2 ★ 录制关键参数（必读）

```bash
lerobot-record \
  --robot.type=so101_follower --robot.id=my_follower \
  --teleop.type=so101_leader --teleop.id=my_leader \
  --dataset.repo_id=soarm101_dorm_act_v1 \
  --dataset.root=/path/to/dorm_data/soarm101_dorm_act_v1 \
  --dataset.single_task="<你的任务描述，如 Pick the pen into the holder.>" \
  --dataset.num_episodes=50 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10 \
  --dataset.video=false \
  --dataset.push_to_hub=false
```

- **`--dataset.video=false` 不能省！** `lerobot-record` 的 `video` 默认是 `True`（会把帧编码成视频）；服务器 torchcodec 损坏读不了视频。**图像（PNG）特征数据集是唯一合法形态。**
- `--dataset.push_to_hub=false`：纯本地采集，不上传 Hub。
- 相机按你的实际配置加（如 `--robot.cameras="{ front: {type: opencv, ...}}"`），相机名会原样进数据集（`observation.images.<名字>`），**在服务器上保持同一命名**。
- 建议每个任务 `num_episodes≥50`（`eval_split=0.13` 时评估集才有意义，见第 10.2 节）。

### 6.3 校验清单（传到服务器后、放行前）

在 `data/raw_inbox/route1_lerobot/soarm101_dorm_act_v1/` 下人工/脚本核对：

1. 目录含 `meta/`、`data/`、`images/`（**不应有 `videos/`**，若有说明录制忘了 `--dataset.video=false` → 建议回炉重传或在宿舍转存为图像特征后重传）；
2. `meta/info.json` 中 `features`：`observation.state` 与 `action` 的 `shape` 为 **6 维**（SO-101 六电机）；相机键为你配置的那几个名字；
3. episode 数量、`meta/episodes.jsonl` 行数与你的采集记录一致；
4. 抽样打开 1–2 张图片确认非全黑/未损坏；
5. 把校验结论写进 `reports/transfer/batch_YYYYMMDD.md`。

### 6.4 放行与就位（服务器上执行）

```bash
ROOT=/home/server/soarm101_dorm
REPO_ID=soarm101_dorm_act_v1

# 1) 放行：inbox → raw（mv，不双份占盘）
mv "$ROOT/data/raw_inbox/route1_lerobot/$REPO_ID" \
   "$ROOT/data/raw/route1_lerobot/$REPO_ID"

# 2) 就位到训练目录（父目录 data/lerobot/ 已存在；目标名用 mv 生成，不要预建空目录）
mv "$ROOT/data/raw/route1_lerobot/$REPO_ID" "$ROOT/data/lerobot/$REPO_ID"
#   若想在 raw/ 留档，改用硬链（省空间）：
#   cp -al "$ROOT/data/raw/route1_lerobot/$REPO_ID" "$ROOT/data/lerobot/$REPO_ID"

# 3) 开训（与路线②同一条，见第 10 章）
bash "$ROOT/scripts/train/train_soarm101_dorm_act_v1.sh"
```

---

## 7. 路线② 落地步骤（自定义 raw 格式）

### 7.1 raw 约定（待你确认宿舍格式后对号入座）

参照 Station Lite 的 raw 形态（每集一个目录：`data.json` + `colors/*.jpg`），但 **字段是 SO-101 单臂 6 维**，示意如下（以最终确认的 schema 为准）：

| 期望字段 | SO-101 含义 | 维度 |
|---|---|---|
| 关节状态 `qpos` | shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll（+gripper） | **6** |
| 动作 `action`/`pose` | 与 state 同构的电机目标位置 | **6** |
| 相机帧 | 每帧各相机一张图（jpg/png） | 按实际相机数 |

> ⚠️ **不要套用 Station Lite 的语义**：它的 `action` 是双臂笛卡尔位姿 + 夹爪开度（米），gripper 常量 `GRIPPER_MAX_OPENING_M=0.08` 是 Station Lite 硬件标定；SO-101 官方语义是**归一化电机位置**（body 关节 degrees 或 ±100 映射，gripper 0–100）。两者不是一套坐标系。

### 7.2 传输与放行

```bash
# 宿舍 → 服务器隔离区（batch 为事务单位）
rsync -avP --info=progress2 /path/to/dorm_raw_batch_001/ \
  server@<SERVER_IP>:/home/server/soarm101_dorm/data/raw_inbox/route2_custom/batch_001/

# 校验通过后放行（服务器上）
mv $ROOT/data/raw_inbox/route2_custom/batch_001 $ROOT/data/raw/route2_custom/batch_001
```

### 7.3 ★ 转换脚本设计（新写，禁改 station 脚本本体）

在 `scripts/convert/` 下新写两支脚本（等 raw schema 确认后动手）：

**① `route2_raw_to_intermediate.py`**：raw episodes → 中间帧表（frames.jsonl + episode_meta + dataset_meta）。
可参照 `lumousTest/20260914/scripts/prepare_act_intermediate.py` 的**流程结构**，但特征契约必须整体替换（见下表）。

**② `route2_intermediate_to_lerobot.py`**：中间 → LeRobotDataset。
**只抄** `/home/server/lumousTest/20260914/scripts/convert_intermediate_to_lerobot.py` 的 API 骨架：

```python
# 骨架要点（抄结构，替换特征表与相机映射）
ds = LeRobotDataset.create(repo_id=..., root=..., fps=..., features=...)  # exist_ok=False！
for frame in frames:
    ds.add_frame(...)
ds.save_episode()
ds.finalize()
```

**6 维特征契约（硬要求）**：

| 项目 | 要求 |
|---|---|
| `observation.state` | `shape=(6,)`，names = shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper |
| `action` | `shape=(6,)`，names 同上 |
| 相机 | 名字按 raw 实配（如 `observation.images.front`），**禁止照抄** cam_high/cam_left_wrist/cam_right_wrist |
| 图像特征 | dtype 用 **image**（禁 `--use-videos` / video 特征） |
| `robot_type` | `"so101"`（示例值，按需） |

- **禁止修改** `lumousTest/20260914/scripts/` 七个 station 脚本本体（保持老师实验可追溯性与 kit 副本一致性）——**抄骨架到本工作区改**。
- `LeRobotDataset.create` 是 **`exist_ok=False`**：输出目录（`data/lerobot/soarm101_dorm_act_v1`）**不得预先存在**，只保证其父目录 `data/lerobot/` 存在。

### 7.4 转换 → 开训

```bash
ROOT=/home/server/soarm101_dorm
REPO_ID=soarm101_dorm_act_v1
PY=/home/server/miniconda3/envs/station_act/bin/python

# raw → intermediate
$PY $ROOT/scripts/convert/route2_raw_to_intermediate.py \
  --input $ROOT/data/raw/route2_custom/batch_001 \
  --output $ROOT/data/intermediate/route2_act/batch_001 \
  2>&1 | tee $ROOT/logs/convert/route2_batch_001_to_intermediate.log

# intermediate → LeRobotDataset（勿预建 --output）
$PY $ROOT/scripts/convert/route2_intermediate_to_lerobot.py \
  --input $ROOT/data/intermediate/route2_act/batch_001 \
  --output $ROOT/data/lerobot/$REPO_ID \
  2>&1 | tee $ROOT/logs/convert/route2_batch_001_to_lerobot.log

# 开训
bash $ROOT/scripts/train/train_soarm101_dorm_act_v1.sh
```

---

## 8. 宿舍 → 服务器传输命令与校验

### 8.1 rsync 模板（在宿舍本机执行）

```bash
# 路线①（LeRobot 数据集目录整传）
rsync -avP --info=progress2 \
  /path/to/dorm_lerobot_dataset/ \
  server@<SERVER_IP>:/home/server/soarm101_dorm/data/raw_inbox/route1_lerobot/soarm101_dorm_act_v1/

# 路线②（raw episodes，按批次目录传）
rsync -avP --info=progress2 \
  /path/to/dorm_raw_batch_001/ \
  server@<SERVER_IP>:/home/server/soarm101_dorm/data/raw_inbox/route2_custom/batch_001/
```

### 8.2 增量/断点注意事项

1. **以 episode/批次目录为事务单位**：禁止边录边传同一集；一批传完再传下一批；
2. **保留时间戳用 `-a`**：二次 rsync 只传增量；
3. **不要加 `--delete`**：避免误删服务器已收批次；
4. 大目录建议加 `--partial --partial-dir=.rsync-partial` 支持断点续传；
5. 同名重传前，先在 inbox 建带日期的 `batch_YYYYMMDD/` 子目录，禁止直接覆盖半包；
6. **未出校验报告不放行**：传完在服务器核对 `du -sh`、文件数、抽样 md5，报告写到 `reports/transfer/batch_*.md`。

```bash
# 传完服务器端快速核对（示例）
ssh server@<SERVER_IP> 'du -sh /home/server/soarm101_dorm/data/raw_inbox/route2_custom/batch_001; \
  find /home/server/soarm101_dorm/data/raw_inbox/route2_custom/batch_001 -type f | wc -l'
```

**红线：传输只写入 `raw_inbox/`，禁止直接写 `raw/` 或 `data/lerobot/`。**

---

## 9. 目录创建指令（mkdir）

> 本工作区已按**方案 A** 创建完毕。以下命令留档，供方案 B 或重建时使用。两段**只差 `ROOT=` 一行**。
> **注意**：刻意**不预建** `data/lerobot/soarm101_dorm_act_v1/` ——`LeRobotDataset.create` 为 `exist_ok=False`，该子目录由转换/移入生成。

### 9.1 方案 A（推荐，已创建）

```bash
ROOT=/home/server/soarm101_dorm

mkdir -p \
  "$ROOT/docs" \
  "$ROOT/data/raw_inbox/route1_lerobot" \
  "$ROOT/data/raw_inbox/route2_custom" \
  "$ROOT/data/raw/route1_lerobot" \
  "$ROOT/data/raw/route2_custom" \
  "$ROOT/data/intermediate/route2_act" \
  "$ROOT/data/lerobot" \
  "$ROOT/scripts/convert" \
  "$ROOT/scripts/train" \
  "$ROOT/scripts/eval" \
  "$ROOT/outputs/soarm101_dorm_act_v1/checkpoints" \
  "$ROOT/logs/transfer" \
  "$ROOT/logs/convert" \
  "$ROOT/logs/train" \
  "$ROOT/reports/transfer" \
  "$ROOT/reports/train" \
  "$ROOT/reports/handover" \
  "$ROOT/inference/server" \
  "$ROOT/inference/client"
```

### 9.2 方案 B（备选）

```bash
ROOT=/home/server/lumousTest/soarm101_dorm

mkdir -p \
  "$ROOT/docs" \
  "$ROOT/data/raw_inbox/route1_lerobot" \
  "$ROOT/data/raw_inbox/route2_custom" \
  "$ROOT/data/raw/route1_lerobot" \
  "$ROOT/data/raw/route2_custom" \
  "$ROOT/data/intermediate/route2_act" \
  "$ROOT/data/lerobot" \
  "$ROOT/scripts/convert" \
  "$ROOT/scripts/train" \
  "$ROOT/scripts/eval" \
  "$ROOT/outputs/soarm101_dorm_act_v1/checkpoints" \
  "$ROOT/logs/transfer" \
  "$ROOT/logs/convert" \
  "$ROOT/logs/train" \
  "$ROOT/reports/transfer" \
  "$ROOT/reports/train" \
  "$ROOT/reports/handover" \
  "$ROOT/inference/server" \
  "$ROOT/inference/client"
```

---

## 10. 训练命令模板（数据就位后开训）

### 10.1 一键启动（已就绪）

```bash
bash /home/server/soarm101_dorm/scripts/train/train_soarm101_dorm_act_v1.sh
```

脚本内容（抄自 `lumousTest/other/deepseek_bash_20260924_6a9d27.sh`，仅改路径/命名）：

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/server/soarm101_dorm          # 方案B: /home/server/lumousTest/soarm101_dorm
REPO_ID=soarm101_dorm_act_v1
DS_ROOT=$ROOT/data/lerobot/$REPO_ID
OUT_DIR=$ROOT/outputs/$REPO_ID
LOG=$ROOT/logs/train/${REPO_ID}.log
cd "$ROOT"

accelerate launch --multi_gpu --num_processes=4 \
  /home/server/miniconda3/envs/station_act/bin/lerobot-train \
  --dataset.repo_id=$REPO_ID \
  --dataset.root=$DS_ROOT \
  --dataset.eval_split=0.13 \
  --policy.type=act \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.chunk_size=50 \
  --policy.n_action_steps=50 \
  --batch_size=4 \
  --num_workers=4 \
  --steps=20000 \
  --log_freq=100 \
  --eval_steps=2000 \
  --save_checkpoint=true \
  --save_freq=2000 \
  --seed=42 \
  --wandb.enable=false \
  --output_dir=$OUT_DIR \
  --job_name=$REPO_ID \
  2>&1 | tee "$LOG"
```

### 10.2 参数说明与变体

| 参数 | 当前值 | 何时改 |
|---|---|---|
| `--dataset.eval_split` | 0.13 | **<20 集时**评估集可能切出 0/1 条，建议 ≥50 集；集少时调小或手动 hold-out |
| `--policy.chunk_size` / `n_action_steps` | 50 / 50 | ACT 范本值；长任务可加大 chunk |
| `--batch_size` | 4 | OOM 时减小 |
| `--steps` / `--save_freq` | 20000 / 2000 | 冒烟先 `--steps=20` |
| `--num_processes=4 --multi_gpu` | 4 卡 | 单卡调试：改 `--num_processes=1` 并去掉 `--multi_gpu` |
| GPU 共享 | — | 开跑前 `nvidia-smi`，别把老师/同学的训练挤爆 |

### 10.3 训后快速确认

```bash
ls /home/server/soarm101_dorm/outputs/soarm101_dorm_act_v1/checkpoints/
# 期望: 0002000 0004000 ... last
ls /home/server/soarm101_dorm/outputs/soarm101_dorm_act_v1/checkpoints/last/pretrained_model
# 期望: config.json model.safetensors policy_pre/postprocessor* train_config.json
```

---

## 11. 隔离原则与硬规则红线

### 11.1 十条红线（务必遵守）

1. **禁止 video 特征 / `--use-videos`**：torchcodec 损坏，全链路用图像特征（路线①录制加 `--dataset.video=false`）。
2. **禁止改动** `/home/server/lumousTest/lin/src/lerobot` 的 git 状态（pinned commit `3f2c29ef7e44b1ddccbcda3b6a63939e53639e9e`）——不 `git pull/checkout`，不重装。
3. **禁止修改/覆盖** `lumousTest/20260914/scripts/` 七个 station 脚本——只允许**抄骨架**到 `soarm101_dorm/scripts/convert/`。
4. **不新建 conda env、不乱装包**：一律用 `station_act`，命令给绝对路径 `/home/server/miniconda3/envs/station_act/bin/...`；勿用 `lerobot` 那个环境（没有 lerobot 包）。
5. **不重装 lerobot**：editable 安装指向 lumousTest，卸载重装会破坏所有人的环境。
6. **一切产物写在 `soarm101_dorm/` 内**；数据必经 `raw_inbox → raw`，禁止跳过校验。
7. **不动他人资产**：`lumousTest/other/id_49_*.tar.xz`、他人数据集/权重/归档一律不删不改。
8. **GPU 共享**：4×5090 多人共用，开跑前 `nvidia-smi`，必要时减 `--num_processes`。
9. **训练用绝对路径**，`cd $ROOT` 后再跑，避免产物散落到 cwd。
10. **冻结基线只读**：`lumousTest/other/requirements.txt` 仅供查版本，不按它在本工作区改环境。

---

## 12. 评估与推理部署预留（后续扩展）

- **真机评估（推荐先做这个）**：用官方闭环——`lerobot-record` + `--policy.path=$OUT_DIR/checkpoints/last/pretrained_model`，repo_id 加 `eval_` 前缀区分（见 AGENT_GUIDE §4）。
- **离线开环评估**：`station_act_offline_eval.py` 写死 14 维，**不可复用**；SO-101 需在 `scripts/eval/` 新写 6 维版，或用 `lerobot-eval`。
- **HTTP 推理服务**：`station_act_http_server.py` 同样写死 14 维，**不可复用**；后续在 `inference/server/` 做 6 维变体（可抄其 FastAPI 骨架），`inference/client/` 放调用端。本阶段只定目录与接口约定。

> 开环指标（L2/MAE 等）只是回归参考，**永远不要当成闭环成功率**汇报。

---

## 13. 磁盘策略与 /mnt 迁移要点

- **默认放 `/` 盘**的 `/home/server/soarm101_dorm/`（余 256G）。参考量级：Station Lite 45 集图像数据集约 23G → SO-101 单臂单相机会小得多，但图像数据集膨胀仍快。
- **何时迁 `/mnt`（1.8T）**：数据集预计 >50G、需要多版本归档、或 `/` 余量 <80G。
- **迁移要点**：
  1. **先停训练**再迁；
  2. `rsync -a /home/server/soarm101_dorm/ /mnt/soarm101_dorm/`；
  3. 可只外置大数据：把 `data/`、`outputs/` 移到 `/mnt/soarm101_dorm_data/` 后在原位留软链（`ln -s`）；
  4. 改 train 脚本里的路径（或软链后不用改）。
- **inbox 一律 `mv` 放行**，不要 cp 双份占盘；raw 存档需要保留时用 `cp -al` 硬链。

---

## 14. 风险清单与 FAQ

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| 1 | torchcodec 损坏 | video 数据集读帧失败 | 全链路图像特征；路线①必须 `--dataset.video=false` |
| 2 | editable lerobot → lumousTest | 动源码毁全服务器环境 | 只读；不 git 操作、不重装 |
| 3 | pinned commit 漂移 | 行为/格式不兼容 | 不改 git 状态；核对 HEAD=`3f2c29ef…` |
| 4 | station 脚本 14 维写死 | 直接跑必报错 | 新写到 `scripts/convert/`，禁改原脚本 |
| 5 | SO-101 特征语义不同 | 电机 6 轴归一化 ≠ Station 笛卡尔位姿 | 按 so_follower 配置写 names，禁混用双臂字段 |
| 6 | GPU 4×5090 共享 | 抢占/OOM/拖死别人 | `nvidia-smi`；减 num_processes |
| 7 | `eval_split=0.13` | 小数据集 eval 空/噪声大 | 建议 ≥50 集；集少改 split |
| 8 | `/` 盘仅余 256G | 图像数据膨胀 | >50G 走 `/mnt`（第 13 章） |
| 9 | 方案 B 误碰老师资产 | 沙盒内误 rm/误改 | 推荐 A；选 B 则置顶"ROOT 外只读" |
| 10 | 数据集布局不符 | 找不到数据 | `--dataset.root` 指向含 `meta/data/images` 的目录 |
| 11 | `LeRobotDataset.create` exist_ok=False | 转换报错 | 不预建数据集目录，只建父目录 |
| 12 | eval/HTTP 脚本不可复用 | 6 维推不起来 | 用 `lerobot-record --policy.path` 真机评估；HTTP 做 6 维变体 |
| 13 | 传输中断出半包 | 脏数据混入 | batch 事务单位 + 校验报告，未出报告不放行 |
| 14 | 误用 `lerobot` conda 环境 | 没有 lerobot 包 | 一律 `station_act` 绝对路径 |

**FAQ**

- **Q: 视频数据集能不能救？** A: 不要赌。torchcodec 在本机是 ABI 级损坏；请在采集端就存图像。
- **Q: 我的 raw 字段和 Station Lite 不一样怎么办？** A: 正常，Station 脚本本来就不适用。把你的 schema 给 Claude/助教，写 `route2_*` 转换脚本即可（第 7 章骨架）。
- **Q: 两条路线的数据能混在一个数据集里训吗？** A: 只要都转成同一 LeRobotDataset 契约（同 6 维语义、同相机命名）就可以合并；不确定时分两个 repo_id 分别训。
- **Q: 训练日志在哪看？** A: `logs/train/soarm101_dorm_act_v1.log`（实时 `tail -f`）。

---

## 附录

### A. 目录速查表

| 我要… | 去哪 |
|---|---|
| 传新数据 | `data/raw_inbox/{route1_lerobot|route2_custom}/batch_*/` |
| 看已校验原始数据 | `data/raw/...` |
| 找训练数据集 | `data/lerobot/soarm101_dorm_act_v1/` |
| 开训 | `scripts/train/train_soarm101_dorm_act_v1.sh` |
| 找权重 | `outputs/soarm101_dorm_act_v1/checkpoints/` |
| 看训练日志 | `logs/train/` |
| 写/看报告 | `reports/{transfer,train,handover}/` |
| 推理部署 | `inference/`（预留） |

### B. 命令速查卡

```bash
# 传输（宿舍端）
rsync -avP --info=progress2 <本地数据>/ server@<IP>:/home/server/soarm101_dorm/data/raw_inbox/route2_custom/batch_001/

# 放行（服务器端）
mv $ROOT/data/raw_inbox/.../batch_001 $ROOT/data/raw/.../batch_001

# 训练
bash /home/server/soarm101_dorm/scripts/train/train_soarm101_dorm_act_v1.sh

# 训后看权重
ls /home/server/soarm101_dorm/outputs/soarm101_dorm_act_v1/checkpoints/
```

### C. SO-101 电机名 / 特征语义

| 电机 | 说明 |
|---|---|
| shoulder_pan | 底座旋转 |
| shoulder_lift | 肩俯仰 |
| elbow_flex | 肘弯曲 |
| wrist_flex | 腕俯仰 |
| wrist_roll | 腕旋转 |
| gripper | 夹爪（0–100 归一化开度） |

state/action 均为这 6 维归一化电机位置（`{motor}.pos`）；与 Station Lite 的双臂笛卡尔位姿+米制开度**完全不同**。

### D. 交接检查清单

- [ ] `data/` 下数据集版本与来源（route/batch）已登记在 `reports/handover/`
- [ ] 当前最优 checkpoint 路径已写明
- [ ] 训练命令可复现（train 脚本 + 本手册第 10 章）
- [ ] 本手册与实际目录一致（改动目录树须更新第 3 章）
- [ ] 硬规则（第 12 章）已知会接手人

### E. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| V1.0 | 2026-09-24 | 初版：服务器现状梳理、隔离目录规划（方案 A/B）、两条数据路线、传输/训练命令、mkdir 指令、硬规则 |
