"""Build the field-ready SO101 Word manual and its Markdown companion."""
from pathlib import Path
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
TITLE = 'SO101 主从臂寝室数据采集操作手册'
CONFIG_PATH = '/home/mingsen/so-ARM101机械臂/scripts/lerobot/fms688.env'
pages = []


def page(title, *blocks): pages.append((title, blocks))
def p(text): return ('p', text)
def h(text): return ('h', text)
def table(head, rows): return ('table', (head, rows))
def step(number, title, when, action, command, success, failure, next_step, config_note=None):
    return ('step', {'number': number, 'title': title, 'when': when, 'action': action,
                     'command': command, 'success': success, 'failure': failure,
                     'next': next_step, 'config_note': config_note})


page(TITLE,
 p('Ubuntu 专用采集机　办公用品三分类　操作版 2.2　2026 年 10 月 8 日'),
 p('本手册用于在寝室固定桌面完成主从臂示教、双相机逐帧图像采集、本地质检、公开上传和网页回看。图像特征写入 LeRobot v3 的 data/Parquet，可直接作为服务器 ACT 训练输入。所有终端命令只在对应正式步骤中出现一次；表格只用于查询、判定和记录。'),
 h('流程索引'),
 table(['步骤范围', '使用时机', '完成条件'], [
  ['A01–A07 首次准备', '新机器、首次接线、设备或校准变化后', '环境、权限、设备、配置、校准及首次验收条件齐全'],
  ['B01–B10 每次采集', '每次正式采集，从开工到上传回看', '当轮关闭、上传有提交编号、网页播放通过'],
  ['C01–C06 异常恢复', '录制、设备、校准或上传异常时', '明确恢复入口后返回指定 B 步骤'],
  ['D01–D04 维护操作', '环境检查、备份、重建或技能刷新时', '维护结果记录完成，采集基线重新确认']]),
 h('日常执行顺序'),
 table(['顺序', '正式步骤', '通过后再继续'], [
  ['1', 'B01 工位复位', '灯光、背景、双臂和双相机位置与登记一致'],
  ['2', 'B02 完整预检', '终端显示 PRE-FLIGHT PASSED'],
  ['3', 'B03 双相机确认', 'top 和 wrist 身份、画面及帧率通过'],
  ['4', 'B04 遥操作确认', '小幅跟随、退出和停机条件通过'],
  ['5', 'B05 初始化与试运行', '轮次身份和待执行命令核对正确'],
  ['6', 'B06 正式录制', '本轮目标数据落盘'],
  ['7', 'B07 落盘判断', '确定回看、续录或异常恢复入口'],
  ['8', 'B08 逐条回看', 'QA.csv 全部人工填写'],
  ['9', 'B09 关闭轮次', '轮次状态为 closed'],
  ['10', 'B10 上传与网页验收', '提交、v3.0 标签和网页播放通过']]),
 p('真实硬件、HF 登录和七条数据闭环以现场验收为准。出现碰撞、失控、异响或拉线风险时，优先执行现场断电和防坠措施；键盘按键不是物理急停。'))

page('A 首次准备一',
 step('A01', '进入固定采集环境',
  '新终端、电脑重启或开始任何 A、B、D 类操作前。',
  '进入工作区，激活已验证的 LeRobot 环境，并在当前终端定义统一入口。日常不自动升级依赖。',
  'cd "$HOME/so-ARM101机械臂"\nsource "$HOME/so101-lab/activate-lerobot.sh"\nso101() {\n  bash "$HOME/so-ARM101机械臂/scripts/lerobot/collect.sh" "$@"\n}',
  '终端显示 LeRobot v0.6.1 环境路径，当前目录为 so-ARM101机械臂，输入 type so101 能看到函数定义。',
  '若激活脚本不存在或导入报错，停止采集并转到 D01。',
  '首次配置继续 A02；日常采集进入 B01。',
  '入口默认读取本机采集配置文件；日常任务参数只修改该文件，不修改 collect.sh 或 collection.py。'),
 step('A02', '配置设备访问权限',
  '本机首次使用，或预检提示当前用户不在 dialout／video 组时。',
  '将当前用户加入串口和视频设备组，注销 Ubuntu 后重新登录，再确认组身份。',
  'sudo usermod -aG dialout,video "$USER"\n# 保存工作后注销 Ubuntu，再重新登录并执行 A01\nid -nG',
  '输出同时包含 dialout 和 video；设备重插后不需要依赖 chmod 666。',
  '若重新登录后仍缺少用户组，核对实际登录用户与系统组配置，不进入真机步骤。',
  '继续 A03。'))

page('A 首次准备二',
 step('A03', '识别真实设备',
  '双臂、顶视或腕部相机首次连接、重接、更换 USB 端口或设备变化后。',
  '一次只插拔一个外接设备，记录稳定的 by-id 路径。分别标记 Leader、Follower、top 和 wrist；遮挡镜头确认相机身份。',
  'so101 devices',
  '得到两个不同的机械臂串口和两个不同的外接相机捕获节点。5959:0107 的 FHD Camera 被识别为笔记本内置摄像头，不用于采集。',
  '若只有内置 FHD、相机附带 ttyACM 或路径随意猜测，保持占位符并停止配置。',
  '继续 A04。',
  '本步只识别设备，不凭设备编号猜测配置值。记录两个串口和两个外接捕获节点后，在 A04 填入 FOLLOWER_PORT、LEADER_PORT、TOP_CAMERA、WRIST_CAMERA。'),
 step('A04', '写入固定配置并登录 HF',
  'A03 获得真实路径后；HF 登录失效时只重复本步骤中的登录部分。',
  '填写双臂串口和腕部相机 by-id；保留固定任务、版本、七条首轮和目标仓库。随后在本机登录 HF，凭据不写入文档、配置或聊天。',
  'nano scripts/lerobot/fms688.env\nhf auth login\nhf auth whoami',
  '身份为 fms688；目标仓库为 fms688/arm101_desktop_collection；配置中没有 Token，所有尖括号设备占位符均已替换。',
  '若身份不是 fms688、无目标仓库写权限或仍有设备占位符，不执行初始化和上传。',
  '继续 A05。',
  '编辑本路径下的实际运行配置。首次必须把 FOLLOWER_PORT、LEADER_PORT、WRIST_CAMERA 的尖括号占位符换成 A03 测得的 by-id；TOP_CAMERA 也须遮挡镜头核实。HF 登录凭据由 CLI 保存，不写进此文件。task-configs/ 中的 .env.example 是其他任务示例，日常入口不会自动读取。'),
 table(['fms688.env 字段', '本次值与修改规则'], [
  ['FMS688_DATA、CALIBRATION_ROOT', '本机数据根目录为 /home/mingsen/fms688_data；校准目录位于其中的 calibration/'],
  ['TASK_SLUG、TASK_DESCRIPTION', 'sort_office_items；英文任务句为 Sort the specified office item into its registered category zone.'],
  ['DATASET_VERSION、ROUND_ID', '首轮 v001、r01；新轮次只改 ROUND_ID；任务、相机布局或校准实质改变时另建版本'],
  ['EPISODES_THIS_ROUND', '首轮填 7；同一轮续录期间不得改变'],
  ['HF_REPO_ID', 'fms688/arm101_desktop_collection；公开上传只使用该仓库'],
  ['FOLLOWER_PORT、LEADER_PORT', '分别填写从臂和主臂的 /dev/serial/by-id/ 实测路径；不能相同'],
  ['FOLLOWER_ID、LEADER_ID', '保留与各自校准 JSON 文件名一致的设备 ID'],
  ['TOP_CAMERA、WRIST_CAMERA', '分别填写顶视海康和腕部 UVC 的 /dev/v4l/by-id/ 捕获路径；内置 FHD 禁用'],
  ['TOP_FOURCC、WRIST_FOURCC；宽高；FPS', '两路 MJPG、640×480，FPS 为 30；只有设备实测支持后才使用'],
  ['EPISODE_MAX_TIME_S、RESET_MAX_TIME_S', '分别为 300 秒和 120 秒硬上限，正常切换用键盘控制'],
  ['MIN_FREE_GB', '当前预检下限 10 GB；按首轮图像特征实际占用提高预留量']]))

page('A 首次准备三',
 step('A05', '核对或生成校准',
  '双臂首次使用、控制板或机械结构变化、校准文件缺失时。已有可靠校准时只做核对，不重复生成。',
  '检查固定校准目录中 Leader 和 Follower 的六关节 JSON。确实缺失时，扶稳机械臂并准备随时断电，按 CLI 提示逐臂校准；不要撞限位或手改 JSON。',
  'source scripts/lerobot/lib.sh\nload_config scripts/lerobot/fms688.env\nls "$CALIBRATION_ROOT/robots/so_follower"\nls "$CALIBRATION_ROOT/teleoperators/so_leader"\n\nlerobot-calibrate \\\n  --robot.type=so101_follower \\\n  --robot.port="$FOLLOWER_PORT" \\\n  --robot.id="$FOLLOWER_ID" \\\n  --robot.calibration_dir="$CALIBRATION_ROOT/robots/so_follower"\n\nlerobot-calibrate \\\n  --teleop.type=so101_leader \\\n  --teleop.port="$LEADER_PORT" \\\n  --teleop.id="$LEADER_ID" \\\n  --teleop.calibration_dir="$CALIBRATION_ROOT/teleoperators/so_leader"',
  '两个 JSON 与配置 ID 同名，每臂包含六个正确关节、完整范围字段且最小值小于最大值；目录已备份。',
  '若身份、关节、方向或范围不可信，停止并转到 C05；不要靠重命名文件消除报错。',
  '继续 A06。',
  '从本配置读取 FOLLOWER_PORT、LEADER_PORT、FOLLOWER_ID、LEADER_ID 和 CALIBRATION_ROOT；校准文件实际位于 /home/mingsen/fms688_data/calibration/robots/so_follower/ 与 teleoperators/so_leader/。已有校准时只核对，不执行重新生成部分。'),
 step('A06', '固定双相机和寝室工位',
  '首次布置、换桌面、换灯位、换相机位置或新数据版本开始前。',
  '固定桌夹、双臂底座、E／S／P 区、台灯、高支架顶视相机和腕部相机。拍摄俯视、腕部及工位全景参考照片并记录本地路径。',
  None,
  '两臂断电下落有承托，断电开关可达；顶视覆盖完整动作区，腕部看得到夹爪与物品，线缆无拉扯；画面无室友、床铺、聊天屏幕或身份信息。',
  '若光照条纹、过曝、反光、遮挡或线缆风险存在，调整后重新登记，不进入采集。',
  '继续 A07。'),
 step('A07', '定义首次遥操作验收',
  '新校准、新设备或工位变化后，在第一次执行日常流程前。',
  '先完成 B01–B03，再在 B04 做首次小幅空载遥操作。首次验收额外确认每个关节方向、夹爪范围、断电和防坠条件。',
  None,
  'B04 首次执行后，双臂方向正确、无抖动异响、退出正常，两路画面随动作更新，腕部线缆不拉紧。',
  '出现反向、撞限位、抖动、异响或下坠风险时立即停止并转到 C05。',
  '首次验收通过后进入 B05；以后每次采集从 B01 开始。'))

page('B 每次采集一',
 step('B01', '复位工位和任务物品',
  '每次正式采集开工时。',
  '使用 A06 的参考照片恢复桌面、灯光、双臂、相机和目标区。准备七种物品，电脑接电并关闭自动休眠。',
  None,
  '布置与登记一致，背景稳定不反光，视野无隐私内容，断电和防坠措施可用。',
  '任何布置发生实质变化时停止本轮，回到 A06 并规划新数据版本。',
  '继续 B02。'),
 table(['首轮 QA 名称', '目标区', '抓取要求'], [
  ['鼠标', 'E 电子区', '关闭电源，夹两侧壳体，避开按键和滚轮'], ['充电宝', 'E 电子区', '无外接线且外壳完好，夹两侧长边'],
  ['U盘', 'E 电子区', '夹主体，保护帽状态全轮一致'], ['带帽笔', 'S 文具区', '笔帽锁紧，夹笔杆中部'],
  ['剪刀', 'S 文具区', '完全闭合且尖端有保护，夹手柄外侧'], ['胶带卷', 'S 文具区', '平放，夹外圆两侧，不保留滚动救援'],
  ['纸巾', 'P 纸品区', '小包装封口完整，夹两侧短边']]),
 step('B02', '执行完整预检',
  'B01 完成后，每次遥操作或录制前。',
  '检查环境版本、用户组、空间、双臂串口、校准、两路相机身份和实际读取；图像特征比 MP4 占空间更多，首轮先量实耗并为本轮预留余量。本步骤不发送电机运动指令。',
  'so101 preflight',
  '最后一行显示 PRE-FLIGHT PASSED，前面没有 FAIL。',
  '按失败项目转到对应 C 步骤；未通过时禁止遥操作和录制。',
  '继续 B03。',
  '本步读取 FMS688_DATA、MIN_FREE_GB、双臂 PORT／ID、CALIBRATION_ROOT、两路 CAMERA／FOURCC／WIDTH／HEIGHT。设备路径或空间阈值不对时，在 A04 修改本配置后重跑预检。'))

page('B 每次采集二',
 step('B03', '确认双相机画面',
  'B02 通过后，每次正式采集前。',
  '同时预览 top 和 wrist，分别遮挡镜头确认身份；观察构图、运动模糊、遮挡、灯光条纹和连续帧率。',
  'so101 cameras --seconds 30',
  '两个不同捕获节点采用 MJPG、640×480、30 FPS；30 秒无掉线，两路平均均不低于 27 FPS，角色与构图正确。',
  '黑屏或占用转到 C03；帧率或灯光问题转到 C04。',
  '继续 B04。',
  '本步读取 TOP_CAMERA、WRIST_CAMERA、TOP_FOURCC、WRIST_FOURCC、TOP_WIDTH／HEIGHT、WRIST_WIDTH／HEIGHT 和 FPS；修改前先按 A03 实测设备支持的格式与节点。'),
 step('B04', '确认遥操作',
  'B03 通过后。首次或设备变化后的执行还承担 A07 验收。',
  '先打印不带相机的命令，确认参数后真正运行并逐关节小幅移动；正常退出后，再打印并运行带两路相机的遥操作。',
  'so101 teleop\nso101 teleop --confirm-physical\nso101 teleop --with-cameras\nso101 teleop --with-cameras --confirm-physical',
  'Follower 跟随方向和夹爪范围正确；画面稳定；Ctrl+C 后设备释放；全过程无碰撞、抖动、异响和拉线。',
  '出现运动风险时先停止动作、支撑机械臂并按现场条件断电，转到 C05。串口或相机被占用时转到 C03。',
  '回到登记起始姿态并继续 B05。',
  '本步读取双臂 PORT／ID、CALIBRATION_ROOT 和 FPS；带相机的两次运行还读取两路 CAMERA／FOURCC／WIDTH／HEIGHT。参数只在本配置中改，改动后从 B02 重验。'))

page('B 每次采集三',
 step('B05', '初始化轮次并核对命令',
  '新轮次第一次录制前；同一轮未录满时不得重复初始化。',
  '创建轮次清单和父目录，再做录制 dry-run。检查 repo_id、数据目录、轮次、目标数、串口、相机、no_stamp 和 --dataset.video=false。',
  'so101 init\nso101 record --dry-run',
  'r01 指向新的数据集路径，目标为七条，repo_id 固定，未提前创建数据集根目录，dry-run 不驱动硬件。',
  '若提示 round already exists，进入 B07 判断；若身份或路径错误，停止并修正 A04。',
  '继续 B06。',
  '本步读取 TASK_SLUG、TASK_DESCRIPTION、DATASET_VERSION、ROUND_ID、EPISODES_THIS_ROUND、HF_REPO_ID 和 FMS688_DATA。首轮应为 sort_office_items／v001／r01／7；新轮次先在本配置改 ROUND_ID，现有轮次续录不得改。'),
 step('B06', '正式录制',
  'B05 核对正确，或 B07 判定同轮可以安全续录后。',
  '把当前物品放在登记起点，保持本机交互式终端。录制后按下表控制阶段；等待每条图像写入 Parquet 完成。',
  'so101 record --confirm-physical',
  '终端打印 saved／remaining；目标 episode 实际落盘；正常结束后提示符恢复且设备释放。',
  '正常提前收工转到 C01；断电或强制终止转到 C02；纯任务失败可按 r 重录，硬件风险必须先停机。',
  '录制进程结束后继续 B07。',
  '本步读取 B05 的任务与轮次字段，另读取 EPISODE_MAX_TIME_S、RESET_MAX_TIME_S、FPS、双臂 PORT／ID、CALIBRATION_ROOT、两路 CAMERA／FOURCC／WIDTH／HEIGHT。正式录制前会重跑预检；同轮续录不得改目标数、硬件或校准。'),
 table(['阶段或按键', '实际行为'], [
  ['录制阶段按 n 或右箭头', '结束本条录制，通常进入 reset；最后一条进入保存收尾'],
  ['reset 阶段按 n 或右箭头', '结束复位，保存本条并继续下一条'],
  ['r 或左箭头', '丢弃当前缓冲并重录；按日志完成复位后重新开始'],
  ['q 或 Esc', '退出循环，但可能保存当前缓冲；不能用来删除失败片段'],
  ['300 秒录制／120 秒复位', '防遗忘硬上限，到时自动推进；不是正常操作节拍'],
  ['reset', '仍运行主从跟随；处理物品前让 Leader 保持安全姿态'],
  ['紧急情况', '键盘不是物理急停；执行现场断电与防坠措施']]))

page('B 每次采集四',
 step('B07', '判断落盘状态和下一入口',
  'B06 返回终端后，尤其是提前退出、中断或不确定保存数量时。',
  '根据终端末尾、SESSION.json 状态和 meta/info.json 的 episode 总数判断结果。不要删除、改名或重新初始化目录。',
  None,
  '能够明确区分：本轮已录满、同轮未录满但数据可读、或数据需要异常恢复。',
  '正常未录满转到 C01；断电或数据读取异常转到 C02；数量超出目标时停止并保留现场证据。',
  '已录满继续 B08；确认可续录时返回 B06。'),
 step('B08', '逐条回看并填写 QA',
  'B07 确认数据可读且有已保存 episode 后。',
  '运行自动验证，再依次查看 QA.csv 列出的每个 episode。确认两路画面、动作、任务、隐私和无救援碰撞，最后填写人工结果。',
  'so101 review\nfor ep in 0 1 2 3 4 5 6; do\n  so101 view --episode "$ep"\ndone\nnano "$HOME/fms688_data/rounds/sort_office_items/v001/r01/QA.csv"',
  '两路图像逐帧可读取，状态与动作值有效；每条 item、result、privacy 和 notes 已按实际情况填写。r02 后使用 QA.csv 的实际 episode 编号。',
  '解码、元数据或数量失败转到 C02；人工失败条目不得改成 pass，也不得直接删除底层文件。',
  '所有目标条目通过后继续 B09。',
  '回看读取本配置的 FMS688_DATA、TASK_SLUG、DATASET_VERSION、ROUND_ID 与 HF_REPO_ID；本轮 QA 文件位于 /home/mingsen/fms688_data/rounds/sort_office_items/v001/r01/QA.csv。新轮次应打开对应 round 目录，并按实际 episode 编号查看。'),
 table(['QA 字段', '填写规则'], [
  ['episode', '保留自动生成编号'], ['item', '使用登记物品名称；首轮七种名称各出现一次'],
  ['result', '完整观看且任务成功才填 pass'], ['privacy', '确认可公开且无他人或敏感信息才填 pass'],
  ['notes', '记录异常或判定依据；含逗号时使用 CSV 双引号']]))

page('B 每次采集五',
 step('B09', '关闭质检通过的轮次',
  'B08 完成，且本轮数量达到目标、每条人工质检通过时。',
  '执行关闭门禁。关闭后该轮不能继续追加；若要采集下一轮，先在配置中设置新的 ROUND_ID，再从 B05 开始。',
  'so101 close',
  '终端显示 ROUND CLOSED，SESSION.json 状态为 closed，数据摘要与最近一次质检一致。',
  '条数、QA 或摘要不一致时返回 B08；封版或隔离状态不得绕过。',
  '准备公开上传时继续 B10；只保留本地时记录收工状态。',
  '关闭时按本配置的 TASK_SLUG、DATASET_VERSION、ROUND_ID、EPISODES_THIS_ROUND 查找本轮清单和 QA；确认当前 ROUND_ID 指向要关闭的轮次，不要为了通过门禁改数量。'),
 step('B10', '上传并完成网页回看',
  'B09 关闭当前轮次、所有轮次均关闭且隐私复核完成后。',
  '上传完整 meta、data（含图像特征）、任务说明和身份文件，保留仓库原 README。上传后记录提交编号，再打开数据集与 LeRobot 查看器检查首尾 episode、两路图像和时间轴。',
  'so101 upload --confirm-public',
  '终端显示 UPLOAD VERIFIED；UPLOAD.json 记录提交编号和 v3.0 格式标签；网页中 top／wrist 图像逐帧可见，状态、动作和时间轴正常。',
  '401、403、断网、提交或标签失败转到 C06；网页异常先用 B08 的本地回看确认数据。',
  '记录浏览日期、提交编号和结果，支撑双臂后按现场流程断电并完成本地备份。',
  '上传读取 HF_REPO_ID、TASK_SLUG、TASK_DESCRIPTION、DATASET_VERSION、ROUND_ID、FMS688_DATA；此处 HF_REPO_ID 必须是 fms688/arm101_desktop_collection。登录身份在 A04 核对，Token 不写入配置。'),
 table(['网页验收项', '通过判据'], [
  ['目标数据集', 'fms688/arm101_desktop_collection 显示本次提交'], ['格式身份', 'v3.0 标签指向 UPLOAD.json 中的提交编号'],
  ['episode', '首条和末条均能选择，数量与本地一致'], ['双相机', 'top 和 wrist 逐帧可见且身份正确'],
  ['时间轴', '切换帧后图像、状态和动作同步显示'], ['隐私', '公开页面无室友、个人信息或无关屏幕内容']]))

page('C 异常恢复一',
 step('C01', '正常提前结束和同轮续录',
  'B06 未录满，但程序正常返回且 B07 能读取已有数据时。',
  '先按 B08 对已落盘部分执行自动验证和查看末尾片段。保持 ROUND_ID、目标数、任务、校准和硬件不变；确认可用后返回 B06，程序会按 saved／remaining 自动补剩余条数。',
  None,
  '已保存数量明确，数据可读，配置指纹未变化；再次录制只补本轮剩余条数。',
  '配置变化、数量异常或数据读取失败时停止续录并转到 C02。',
  '返回 B06；录满后按 B07–B10 完成。'),
 step('C02', '断电 强制终止或数据异常',
  '录制时断电、进程被杀、目录无元数据、解码失败或数量无法解释时。',
  '先确保机械臂安全并断电。保留数据集、轮次目录、SESSION.json 和终端错误末尾；不要删除残留、重命名目录或重新 init。使用 B08 的自动检查确定可读边界。',
  None,
  '维护者能够解释 meta/info.json、文件和 SESSION.json 的一致状态，并明确恢复或另建清洗版本的方案。',
  '没有可验证恢复方案时保持原件不动，不继续写入，也不上传。',
  '确认可续录时转 C01；需要清洗时建立独立版本后重新从 A04 规划。'),
 step('C03', '相机黑屏 占用或身份错误',
  'B02、B03 或 B04 提示设备不存在、busy、黑屏、重复设备或识别为内置 FHD 时。',
  '关闭占用相机的预览或录制程序；检查 USB 线、端口和捕获节点。按 A03 重新插拔并遮挡镜头确认，必要时按 A04 更新 by-id。',
  None,
  '两个外接捕获节点不同，top／wrist 遮挡结果正确，内置 FHD 未被使用。',
  '真正腕部相机未接入时保持待验收，不用内置摄像头代替。',
  '返回 B02，再执行 B03。'))

page('C 异常恢复二',
 step('C04', '帧率 灯光或画面质量异常',
  'B03 任一路低于 27 FPS，或出现条纹、闪烁、模糊、反光、过曝和遮挡时。',
  '核对 MJPG、640×480、30 FPS；避免 USB 带宽不足的 Hub；固定台灯电源、档位和方向，调整背景、焦点及镜头角度。只有设备暴露相应控制时才设置防闪烁频率。',
  None,
  '静止和缓慢运动画面稳定，两路实测均不低于 27 FPS，夹爪与目标清晰。',
  '无法稳定时更换连接或设备，并回到 A03／A06 重新登记。',
  '返回 B03 重新执行 30 秒测试。'),
 step('C05', '校准变化或遥操作异常',
  '校准缺失、指纹变化、关节反向、撞限位、抖动、异响或腕部拉线时。',
  '停止运动并按现场条件断电；保存错误和设备身份。核对 A04 的 ID、A05 的原校准备份及 A06 的线缆布置。当前轮次开始后不得替换校准继续写入。',
  None,
  '原因明确，校准和设备身份可信；重新执行 A07 的首次验收要求后无异常。',
  '无法确认时保持真机停用，不通过改 JSON 或重命名文件绕过。',
  '硬件与校准未变时返回 B02；发生实质变化时建立新数据版本。'),
 step('C06', '上传或网页回看失败',
  'B10 遇到 401、403、断网、远端并发、提交或标签中断，或网页缺少图像时。',
  '保留本地原件和 UPLOAD.json。确认 A04 的 fms688 身份与写权限；检查远端是否已有提交及 v3.0 标签。网络或权限恢复后重新执行 B10，脚本会重新校验本地摘要和远端父提交。',
  None,
  'UPLOAD VERIFIED、提交编号和 v3.0 标签一致，网页实际播放通过。',
  '远端数据比本地更新、身份不同或包含额外数据文件时停止，禁止覆盖或混入其他任务。',
  '成功后完成 B10 的浏览记录和收工。'),
 table(['需要保留的异常证据', '内容'], [
  ['时间与步骤', '发生时间、A／B／C 步骤编号'], ['终端', '执行入口和错误末尾；不得包含 Token'],
  ['数据身份', '任务、版本、round、episode 数量'], ['设备', '双臂及相机 by-id、当时连接方式'],
  ['画面', '黑屏、条纹、遮挡或异常动作现象；不得公开室友画面']]))

page('D 维护操作一',
 step('D01', '检查固定环境',
  'A01 激活失败、导入报错、依赖异常，或计划开始新的采集阶段时。',
  '在 A01 已激活的终端检查 Python、LeRobot、CPU 依赖、磁盘和 HF 身份。本命令不驱动硬件。',
  'so101 doctor',
  'Python 3.12.14、LeRobot 0.6.1、CPU torch 2.11.0、torchvision 0.26.0、torchcodec 0.11.1，pip check 无损坏；磁盘空间足够。HF 未登录只影响 A04／B10。',
  '版本或依赖不符时不要现场升级；保留输出并评估 D03 的候选环境重建。',
  '环境通过后返回 A01；HF 未登录转 A04。',
  '本步读取 FMS688_DATA 计算磁盘剩余量；若要调整预检下限则在本配置修改 MIN_FREE_GB。软件版本由 A01 激活的 /home/mingsen/so101-lab 环境决定，不通过本配置修改。'),
 step('D02', '记录版本并完成本地备份',
  '环境确认可用后、每轮收工后和任何维护前。',
  '导出依赖版本并计算清单摘要。将 fms688_data 下 datasets、rounds、calibration 复制到外接盘的 SO101_backups／日期目录；不复制 HF 登录缓存。',
  'python -m pip freeze > "$HOME/so101-lab/requirements-collector.lock.txt"\nsha256sum "$HOME/so101-lab/requirements-collector.lock.txt"',
  '版本清单和摘要已记录；外接盘备份的文件数、体积一致，并抽样读取 Parquet 中的双相机图像和 JSON。',
  '备份未核验时保留本地原件，不删除或迁移当前数据。',
  '无后续维护时结束；需要重建进入 D03。'))

page('D 维护操作二',
 step('D03', '在候选目录重建环境',
  '固定环境不可恢复，或确需验证新机器／新候选目录时。不得在正式录制过程中执行。',
  '在已检出的 LeRobot v0.6.1 源码目录创建独立 Python 3.12 环境，一次性安装固定 CPU 依赖和采集 extra。保留原环境，候选环境通过全套测试后才切换。',
  'uv venv --python 3.12 --seed .venv\nsource .venv/bin/activate\npython -m pip install \\\n  --index-url https://pypi.org/simple \\\n  --extra-index-url https://download.pytorch.org/whl/cpu \\\n  "torch==2.11.0+cpu" "torchvision==0.26.0+cpu" \\\n  -e ".[core_scripts,feetech]"',
  'D01 版本全部匹配，回归测试和临时 LeRobot 数据测试通过，旧环境和校准备份仍可恢复。',
  '依赖漂移、图像读取或测试失败时放弃候选环境，不改正式激活入口。',
  '通过后更新维护记录，再从 A01 开始完整验收。'),
 step('D04', '安装或刷新 HF CLI 技能',
  '新用户环境首次安装，或 hf CLI 确实升级后。日常采集不重复执行。',
  '将与当前 CLI 匹配的官方技能安装到用户级目录；只有 CLI 升级后才刷新。下一轮 Codex 检查技能发现结果。',
  'hf skills add --global\n# 仅在 hf CLI 确实升级后执行\nhf skills update --global',
  '用户目录存在 hf-cli/SKILL.md，内容标注 huggingface_hub 1.32.0；新一轮技能列表能发现 hf-cli。',
  '技能缺失只影响助手使用 CLI 的指导，不替代 A04 的账号登录；安装失败时保留 CLI 原状态。',
  '返回 D01 检查环境，随后按需要进入 A 或 B 流程。'),
 table(['目录', '用途'], [
  ['$HOME/so-ARM101机械臂', '正式手册、任务配置、采集脚本和验证记录'], ['$HOME/so101-lab', 'LeRobot 源码、独立环境、激活脚本和依赖清单'],
  ['$HOME/fms688_data', '数据集原件、轮次记录和校准文件'], ['$HOME/.agents/skills/hf-cli', 'Codex 使用的 HF CLI 技能'],
  ['$HOME/.cache/huggingface', 'Hub 缓存与登录信息；不得公开或整体备份']]))

page('任务定义与最终验收',
 h('固定任务和数据边界'),
 table(['项目', '固定内容'], [
  ['任务文字', 'Sort the specified office item into its registered category zone.'], ['首轮', 'v001／r01，共七条；七种物品各一条'],
  ['数据仓库', 'fms688/arm101_desktop_collection；不混入蓝方块或 USB 插入任务'], ['保存顺序', '先本地保存和逐条质检，关闭轮次后单独公开上传'],
  ['隐私', '公开前排除室友、床铺、个人信息和无关屏幕内容'], ['数据意义', '七条用于验证采集闭环，不代表训练数据已经足够']]),
 h('现场验收记录'),
 table(['验收项', '应保留的证据', '当前状态'], [
  ['环境与技能', 'D01 输出、hf-cli/SKILL.md、下一轮技能发现', '环境和技能已安装；HF 登录待完成'],
  ['双臂与校准', 'by-id、校准备份、ID、A07 结果', '待现场验收'],
  ['双相机与灯光', 'B03 的 30 秒结果、角色遮挡、FPS 和参考照片', '腕部待接入验证'],
  ['七条录制与质检', 'meta/info.json、QA.csv、VALIDATION.json', '待现场验收'],
  ['公开上传', 'UPLOAD.json 的提交编号和 v3.0 标签', '待真实数据与登录'],
  ['网页回看', '浏览日期、提交编号、首尾集和两路画面结果', '待上传后验收']]),
 h('软件验证说明'),
 p('当前软件测试使用临时合成数据和模拟硬件／网络接口，不属于真实示教。测试已覆盖新建、双相机图像特征、同轮续录、逐帧读取、人工质检门禁、封版和隔离拦截、内置摄像头拒绝、上传失败与标签失败重试。'),
 h('资料入口'),
 p('LeRobot v0.6.1：https://github.com/huggingface/lerobot/tree/v0.6.1\n数据工具：https://huggingface.co/docs/lerobot/using_dataset_tools\nHF CLI 技能：https://huggingface.co/docs/hub/agents-cli\n子豪兄回看：https://zihao-ai.feishu.cn/wiki/IFUqwVBCjiJpX8kEav8clrmUnpc'),
 p('旧采购、装配、训练和服务器文档保留作专题背景。日常采集只按本手册 B01–B10 执行；异常时转到明确的 C 步骤。'))


def set_font(run, name, size=None, bold=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), name)
    if size: run.font.size = Pt(size)
    if bold is not None: run.bold = bold


def add_labeled(doc, label, text):
    para = doc.add_paragraph(); para.paragraph_format.space_after = Pt(4)
    run = para.add_run(label + '：'); run.bold = True; para.add_run(text)


def add_code(doc, text):
    para = doc.add_paragraph(); para.paragraph_format.space_before = Pt(2); para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.02; para.paragraph_format.keep_together = True
    shade = OxmlElement('w:shd'); shade.set(qn('w:fill'), 'F2F4F5'); para._p.get_or_add_pPr().append(shade)
    set_font(para.add_run(text), 'DejaVu Sans Mono', 8.0)


def add_table(doc, heads, rows):
    tab = doc.add_table(rows=1, cols=len(heads)); tab.style = 'Table Grid'; tab.autofit = False
    widths = [5.7, 11.7] if len(heads) == 2 else [4.0, 8.4, 5.0]
    if heads[0] == '顺序': widths = [1.2, 6.2, 10.2]
    if heads[0] == '首轮 QA 名称': widths = [4.0, 3.0, 10.4]
    if heads[0] == 'QA 字段': widths = [3.8, 13.6]
    for column, width in zip(tab.columns, widths): column.width = Cm(width)
    borders = OxmlElement('w:tblBorders')
    for side in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        edge = OxmlElement('w:' + side)
        for key, value in [('val', 'single'), ('sz', '4'), ('color', 'D9D9D9')]: edge.set(qn('w:' + key), value)
        borders.append(edge)
    tab._tbl.tblPr.append(borders)
    for cell, label in zip(tab.rows[0].cells, heads): cell.text = label
    repeat = OxmlElement('w:tblHeader'); tab.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in rows:
        for cell, value in zip(tab.add_row().cells, values): cell.text = value
    for ri, row in enumerate(tab.rows):
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for ci, cell in enumerate(row.cells):
            cell.width = Cm(widths[ci]); cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if ri == 0:
                shade = OxmlElement('w:shd'); shade.set(qn('w:fill'), 'E7EBEF'); cell._tc.get_or_add_tcPr().append(shade)
            for para in cell.paragraphs:
                para.paragraph_format.space_before = Pt(3); para.paragraph_format.space_after = Pt(4); para.paragraph_format.line_spacing = 1.05
                for run in para.runs: set_font(run, 'Noto Sans CJK SC', 9, ri == 0)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def validate_source():
    forbidden = ('上述命令', '以下操作', '按前页', '按第 ')
    terminal_prefixes = ('so101 ', 'hf auth', 'hf skills', 'lerobot-', 'python ', 'source ', 'sudo ', 'nano ', 'bash ', 'cd ', 'uv ', 'id -nG', 'sha256sum ')
    step_ids, commands = [], []
    for _, blocks in pages:
        for kind, content in blocks:
            if kind == 'step':
                step_ids.append(content['number'])
                assert not any(word in ' '.join(str(v) for v in content.values() if v) for word in forbidden)
                if content['command']:
                    commands.extend(line.strip() for line in content['command'].splitlines()
                                    if line.strip() and not line.lstrip().startswith('#') and line.strip() not in ('done', 'so101() {', '}'))
            elif kind == 'table':
                heads, rows = content; joined = ' '.join(heads + [cell for row in rows for cell in row])
                assert not any(prefix in joined for prefix in terminal_prefixes), f'Command-like text in table: {joined}'
            elif kind == 'p':
                assert not any(word in content for word in forbidden), content
    expected = [f'A{i:02d}' for i in range(1, 8)] + [f'B{i:02d}' for i in range(1, 11)] + [f'C{i:02d}' for i in range(1, 7)] + [f'D{i:02d}' for i in range(1, 5)]
    assert step_ids == expected, (step_ids, expected)
    configured = {'A01', 'A03', 'A04', 'A05', 'B02', 'B03', 'B04', 'B05',
                  'B06', 'B08', 'B09', 'B10', 'D01'}
    documented = {content['number'] for _, blocks in pages for kind, content in blocks
                  if kind == 'step' and content['config_note']}
    assert configured == documented, (configured - documented, documented - configured)
    duplicates = sorted({line for line in commands if commands.count(line) > 1 and not line.endswith('\\')})
    assert not duplicates, f'Duplicate command lines: {duplicates}'


def build():
    validate_source(); doc = Document()
    for border in doc.styles.element.xpath('.//w:pBdr'): border.getparent().remove(border)
    section = doc.sections[0]; section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.45); section.left_margin = section.right_margin = Cm(1.8)
    for name in ['Normal', 'Title', 'Heading 1', 'Heading 2']:
        style = doc.styles[name]; style.font.name = 'Noto Sans CJK SC'; style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Noto Sans CJK SC'); style.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles['Normal'].font.size = Pt(9.6); doc.styles['Normal'].paragraph_format.space_after = Pt(5); doc.styles['Normal'].paragraph_format.line_spacing = 1.08
    doc.styles['Title'].font.size = Pt(23); doc.styles['Heading 1'].font.size = Pt(18); doc.styles['Heading 2'].font.size = Pt(12.5)
    for name in ['Heading 1', 'Heading 2']:
        doc.styles[name].paragraph_format.space_before = Pt(5); doc.styles[name].paragraph_format.space_after = Pt(5)
    footer = section.footer.paragraphs[0]; footer.alignment = 2; footer.add_run('SO101 采集操作版 2.2   |   ')
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE'); footer._p.append(field)
    for run in footer.runs: set_font(run, 'Noto Sans CJK SC', 8)
    md = []
    chapter_starts = {'A 首次准备一'}
    for page_index, (page_title, blocks) in enumerate(pages):
        heading = doc.add_paragraph(page_title, 'Title' if page_index == 0 else 'Heading 1')
        if page_title in chapter_starts: heading.paragraph_format.page_break_before = True
        heading.paragraph_format.keep_with_next = True
        md.append('# ' + page_title)
        for kind, content in blocks:
            if kind == 'p': doc.add_paragraph(content); md.append(content)
            elif kind == 'h': doc.add_paragraph(content, 'Heading 2'); md.append('## ' + content)
            elif kind == 'table':
                heads, rows = content; add_table(doc, heads, rows)
                md += ['| ' + ' | '.join(heads) + ' |', '| ' + ' | '.join(['---'] * len(heads)) + ' |']
                md += ['| ' + ' | '.join(cell.replace('\n', '<br>') for cell in row) + ' |' for row in rows]
            elif kind == 'step':
                doc.add_paragraph(f"{content['number']} {content['title']}", 'Heading 2'); md.append(f"## {content['number']} {content['title']}")
                for label, key in [('什么时候执行', 'when'), ('操作', 'action')]:
                    add_labeled(doc, label, content[key]); md.append(f'**{label}：** {content[key]}')
                if content['command']:
                    add_labeled(doc, '执行命令', '复制整个代码块执行。'); add_code(doc, content['command'])
                    md += ['**执行命令：** 复制整个代码块执行。', '```bash\n' + content['command'] + '\n```']
                else:
                    add_labeled(doc, '执行命令', '无。本步骤为现场操作或判断。'); md.append('**执行命令：** 无。本步骤为现场操作或判断。')
                if content['config_note']:
                    note = f"{CONFIG_PATH}。{content['config_note']}"
                    add_labeled(doc, '配置文件与参数', note)
                    md.append(f'**配置文件与参数：** {note}')
                for label, key in [('成功判据', 'success'), ('失败时转到', 'failure'), ('完成后进入下一步', 'next')]:
                    add_labeled(doc, label, content[key]); md.append(f'**{label}：** {content[key]}')
            md.append('')
    doc.core_properties.title = TITLE; doc.core_properties.author = 'fms688'
    docx = ROOT / (TITLE + '.docx'); doc.save(docx)
    (ROOT / (TITLE + '.md')).write_text('\n\n'.join(md), encoding='utf-8')
    print(docx)


if __name__ == '__main__': build()
