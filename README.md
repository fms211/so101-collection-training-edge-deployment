# SO-101 采集、训练与jetson orin NX本地推理工作流

这个仓库整理 SO-101 主从臂项目的代码、操作手册和数据迁移工具，按三阶段使用：

1. [采集与审核](阶段指南/01-采集.md)：笔记本连接两臂及两台相机，录制、回放、质检和封存。
2. [数据迁移与训练](阶段指南/02-训练.md)：按完整任务和版本打包，在训练服务器校验读回并进行 ACT 训练。
3. [Jetson 推理](阶段指南/03-推理.md)：从服务器转移 checkpoint，先离线检查，再由现场人员监督实机运行。

## 运行依赖

从零安装采集笔记本、训练服务器与 Jetson 的系统工具和独立 Python 环境，请先看 [三端依赖安装教程（新手版）](环境依赖/三端安装教程.md)。[三端运行依赖与检查](环境依赖/三端运行依赖.md)提供版本细节和采集机 pip 快照。

## 下载并在三端使用

仓库目前是**私有仓库**。笔记本、训练服务器和 Jetson 分别需要有权访问 `fms211` 账号下的本仓库，并配置各自的 GitHub 认证；登录网页不会自动让终端 Git 获得权限。先用 SSH 克隆（需要在各设备配置并授权自己的 SSH 密钥）：

```bash
cd "$HOME"
git clone git@github.com:fms211/so101-collection-training-edge-deployment.git
cd "$HOME/so101-collection-training-edge-deployment"
```

也可使用 HTTPS：`git clone https://github.com/fms211/so101-collection-training-edge-deployment.git`，按终端提示使用 GitHub 支持的认证方式。不要把密码、Token 或 SSH 私钥写入仓库或聊天。如果某台设备不能访问 GitHub，可由已登录的笔记本下载代码后，通过可信连接把仓库代码拷到该设备；数据集和模型仍须按下文另行迁移。

| 设备 | 主要用途 | 从仓库使用的内容 | 还需准备 |
| --- | --- | --- | --- |
| 笔记本 | 主从臂与双相机采集、回放、审核、打包 | `scripts/lerobot/`、`数据打包工具/` | LeRobot 0.6.1、设备权限、校准、独立本地配置与本地 SSD |
| 训练服务器 | 接收数据、读回验证、ACT 训练 | `数据打包工具/服务器_校验解包.py` 和服务器适配指南 | 服务器现有 `station_act` 环境、已审核数据包、空闲 GPU 和独立输出目录 |
| Jetson | 使用 checkpoint 做离线检查和受监督的从臂推理 | `scripts/jetson/`、`scripts/lerobot/collection.py` | Jetson 专用运行环境、完整 checkpoint、从臂标定及两路相机 |

Git 仓库只同步代码与手册：**采集数据和模型不会随 `git clone` 下载**。实际流程为笔记本完成采集与 QA → 将完整任务/版本的数据包传给服务器校验并训练 → 选择完整 checkpoint 经笔记本中转到 Jetson；再按[推理指南](阶段指南/03-推理.md)验证模型、关节和相机。每台设备更新代码时，在各自仓库目录执行 `git pull --ff-only`；请先保存自己的本地修改，不要用更新覆盖配置或数据。

### 笔记本：启动自动化采集菜单

```bash
cd "$HOME/so101-collection-training-edge-deployment"
# 首次创建本地配置；已存在时不覆盖
if [ ! -e scripts/lerobot/fms688.env ]; then
  cp scripts/lerobot/fms688.env.example scripts/lerobot/fms688.env
fi
${EDITOR:-nano} scripts/lerobot/fms688.env
# 原采集笔记本已配置此激活脚本；其他机器先自行准备 LeRobot 0.6.1 环境
source "$HOME/so101-lab/activate-lerobot.sh"
bash scripts/lerobot/interactive_collection.sh
```

在配置中填写本机的数据目录、任务/版本、主从臂串口和两路相机；优先使用 `/dev/serial/by-id/`、`/dev/v4l/by-id/`。也可先激活自己安装的 0.6.1 环境，再启动菜单。采集选项 3 需要图形桌面、`gnome-terminal` 和 `script`，会进入日期任务选择和预检；菜单 1、3、4、5、11、6 分别用于预检、采集、检查、回放、填写 QA 和关轮。录制控制窗口按提示输入 `s`、`n`、`r`、`q` 后回车；`q` 不是急停。详见[采集阶段指南](阶段指南/01-采集.md)和[交互采集助手](SO101_交互采集助手.md)。

实时画面和已保存轨迹如何查看，见 [Rerun 可视化界面与轨迹回放](阶段指南/04-Rerun可视化.md)。

自动化入口及调用关系：`interactive_collection.sh` → `configure_collection.py` → `preflight_collection.sh` / `init_round.sh` → `record_terminal.sh` / `record_round.sh` → `record_sent_action.py`。审核、封存、同步等脚本在同一 `scripts/lerobot/` 下；工具保留保护与人工确认步骤，不会自动替代现场验收。

### 训练服务器和 Jetson：从哪里开始

服务器进入克隆目录后先读[数据打包和服务器解包](数据打包工具/README_数据打包与服务器解包.md)及 [SO-101 服务器适配指南](首次Act训练文本情况.txt/SO101_数据集判定与ACT训练服务器适配指南.md)。解包脚本校验包和逐文件摘要；用服务器现有环境读回两路图像与六维动作后，先小步数冒烟，再决定正式训练。`train_act.sh` 等启动器也在仓库中，它们依赖自身配置与数据路径，使用前通过 `--help` 和 `--dry-run` 检查，不应直接套用到服务器已有的训练任务。

Jetson 进入自己的克隆目录后读[推理指南](阶段指南/03-推理.md)和[完整手册](SO101采集-回放-打包-训练-本地推理全流程.md)。先准备该机已验证的 Jetson 环境与完整 `pretrained_model` 目录；模型先从服务器传到笔记本，再从笔记本传到 Jetson。按[离线检查示例](阶段指南/03-推理.md#无硬件离线检查示例)使用 `scripts/jetson/offline_act_check.py` 做无硬件检查；受控实机脚本引用的 `collection.py` 在 `scripts/lerobot/`。仓库不会自动安装 Jetson 的专用 GPU 启动器；`run_guarded_limit5.sh` 带原机路径，必须根据现场环境核对，不能直接照搬。

[完整操作手册](SO101采集-回放-打包-训练-本地推理全流程.md) 保留原始命令、历史记录与排障；其中绝对路径是原设备示例，使用前按机器修改。采集与训练环境分别为笔记本 LeRobot 0.6.1、服务器已有的 0.6.2 环境；不要覆盖服务器既有环境或其他项目数据。数据图像保存在 LeRobot v3 Parquet 中。

| 目录 | 内容 |
| --- | --- |
| `scripts/lerobot/` | 采集、审查、同步、封存及训练脚本与测试 |
| `数据打包工具/` | 完整任务版本打包及服务器校验解包 |
| `scripts/jetson/` | ACT 离线检查及受控实机推理脚本 |
| `首次Act训练文本情况.txt/` | SO-101 服务器适配资料，部分是规划或历史记录 |
| `assets/` | 手册引用的图片 |

数据集、模型、个人配置、凭据及运行日志不纳入仓库。本仓库不包含上游 SO-ARM100 硬件仓库；硬件资料参见 [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100)。

**现场状态**：此前从臂关节 3 响应异常，采集、抓取和引导校准尚未完成现场验收；最近 Jetson 短时试运行未完成抓取。任何实际电机动作前须确认设备、周围空间、人员监督及停止方式。`MAX_RELATIVE_TARGET` 限制目标与当前位置的差值，不是速度限制。
