from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget, QSizePolicy, QPlainTextEdit, QVBoxLayout
from qfluentwidgets import BodyLabel, SettingCardGroup

from ok.gui.about.ProjectCard import ProjectCard
from ok.gui.about.VersionCard import VersionCard
from ok.gui.util.app import get_localized_app_config
from ok.gui.util.pyappify_startup import get_startup_version_change
from ok.gui.widget.Tab import Tab
from ok.util.file import get_path_relative_to_exe


class AboutTab(Tab):
    def __init__(self, config):
        super().__init__()
        self.version_card = VersionCard(config, get_path_relative_to_exe(config.get('gui_icon')),
                                        config.get('gui_title'), config.get('version'),
                                        config.get('debug'), self)
        # The About page uses the same section rhythm as the rest of the app.
        self.add_widget(self.version_card)

        if version_change := get_startup_version_change():
            update_note_label = BodyLabel()
            update_note_label.setText(self._format_update_note(version_change.content))
            update_note_label.setWordWrap(True)
            update_note_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            update_note_label.setContentsMargins(0, 0, 0, 0)
            self.add_card(self._startup_version_change_title(version_change), update_note_label)

        # 更新日志（全历史 + 原版更新提醒）
        self._add_update_log_card()
        # 作者的话
        self._add_author_card()

    def _add_update_log_card(self):
        try:
            update_log_text = QPlainTextEdit()
            update_log_text.setReadOnly(True)
            update_log_text.setMaximumHeight(220)
            upstream_note = ''
            try:
                from src.upstream_check import has_upstream_update
                has_upd, msg, found_date = has_upstream_update()
                if has_upd:
                    upstream_note = f'【⚠️ 原版 okww 有更新】\n检测到原版更新（{found_date}）：{msg}\n请及时检查合并原版更新内容\n\n'
            except Exception:
                pass
            update_log_text.setPlainText(upstream_note + self.tr(
                'V1.30.03：修复代理自愈回归测试在 GitHub Actions Windows 环境中因用户目录长路径与 8.3 短路径表示不同而误判失败；产品代理选择逻辑不变。本次仅进行离线测试，未启动或操控游戏。\n'
                'V1.30.02：修复打包版连接 GitHub 偶发失败：每次启动按 Windows 系统代理优先、常见端口候补的顺序实际请求 GitHub，只有请求成功才写入仓库 http.proxy；端口开放但无法访问 GitHub 时自动跳过，所有候选失效时移除残留代理。打包启动器会在 Fetch 前执行检测，主程序和原版更新检查复用同一逻辑，并记录 proxy_bootstrap.log。仅进行离线测试与 GitHub 连通性验证，未启动或操控游戏。\n'
                'V1.30.01：修复每周乐园错过设定检查日后不再检查的问题：设定日期现在是本周最早检查日，只要当前账号尚无本周“每周乐园”完成记录，之后每次执行每日任务都会继续补检；确认乐园已完成或自动乐园成功结束后才写入账号级记录并停止本周重试。检查失败、中断、旧周记录或无效记录不会阻止下次补检；设置为“无”时仍从周日开始。全程仅做离线单元测试，未启动或操控游戏。\n'
                'V1.30.00：重整账号配置与多账号轮换：账号页新增可编辑的新账号任务模板及新建账号入口，新账号只需填写短名、手机号、游戏昵称、特征码、可选备用识别名和所属序列；备用识别名可停用并保留文字，周常乐园检查日等选择框不再被鼠标滚轮误改。序列页精简为新建、删除和账号上下移动。明确选择“当前执行账号”后，程序把当前世界账号视为该账号并直接执行，按序列循环后登录回起始账号，运行期间不再覆盖该设置；留空继续使用原有退登识别。新增 UUID 防注入、修订冲突、身份重复回滚和模板配置包往返测试。本次仅做离线验证，未启动或操控游戏。\n'
                'V1.29.00：修复自动深渊把已经通关的楼层误判为可挑战并从第一层重复开打：逐层选中楼层后以“重置”为最强完成证据，并检测楼层行中的角色头像；锁标识用于确认未解锁，选中行同时出现“挑战开始”且没有头像或重置时才判为可挑战。三塔 n/12 星数只用于发现冲突，不单独决定完成状态；证据冲突会等待稳定后复扫一次，仍不一致则标记为状态未知并整塔安全跳过，不进入角色扫描、编队或战斗。扫描过程只点击楼层行，不点击重置或挑战按钮。本次仅做离线截图与单元测试，未启动或操控游戏。\n'
                'V1.28.02：修复自动深渊扫描深境之塔时误报“关卡存在性识别不连续”：当可挑战首层的圆形楼层数字 OCR 漏识别、但后续锁定或完成标记能证明更高楼层存在时，依据深塔楼层必定从第一层连续排列的特性，按连续规则补全此前楼层；仍保留完全没有关卡证据时的停止保护，并记录原始存在性结果和补全范围。离线验证未执行游戏内流程。\n'
                'V1.28.01：自动深渊补充分辨率自适应：支持不低于 1280×720 的标准 16:9 捕获帧，覆盖 720P、900P、1080P、1440P 和 3840×2160；任务在首次游戏操作前校验捕获帧，非16:9、低分辨率或空帧直接停止。角色头像模板随帧高缩放，局部 OCR 只按需要放大，避免720P模板过大和4K画面固定放大造成额外开销。离线验证未执行游戏内流程。\n'
                'V1.28.00：自动深渊扩展为三塔完整流程：可选两侧塔优先或中间塔优先，先扫描三塔实际存在的 1～4 层，再按每塔剩余消耗重新识别角色体力并自动编队；左右塔按 1/2/3/4、中塔按每层 5 点预算。进入挑战后识别环境特性并关闭提示，启动自动战斗；成功时继续挑战或返回深塔，失败时跳过本塔剩余关卡，体力或角色不足时安全返回并继续下一塔。角色死亡不会触发通用传送复活。本次只完成离线验证，未执行游戏内流程。\n'
                'V1.27.01：修复自动深渊已选中角色仍报编号验证失败：编号识别改为覆盖卡片外沿的右上徽章并提取深灰底上的白色 1/2/3；首次等待超时后重新扫描实际选择状态，确认成功则继续，状态不明则截图停止且不重复点击，避免把已选角色取消。离线验证未启动或操控游戏。\n'
                'V1.27.00：自动深渊新增单队自动编队：完整三人预设优先，缺员时保护完整队和两人核心并按定位选择替补；严格区分光主、风主和未知形态，先清除已有选择，再跨页点击并逐个验证 1/2/3。三个编号正确后只点击“完成”并停在编辑队伍页，不会点击开启挑战、不会进入战斗。离线验证未启动或操控游戏。\n'
                'V1.26.02：修复自动深渊将单页角色列表误判为滚动失败：用右侧滚动滑块覆盖率确认单页，直接使用第一屏并尝试识别底部可见卡片；多页滚动无效仍保留错误保护。离线验证未启动或操控游戏。\n'
                'V1.26.01：自动战斗正常收尾提速：首次重新索敌计入原有 6 秒观察窗，目标持续消失且当前帧没有复活框时不再额外阻塞 2 秒；正常击杀改记战斗时长和结束原因，已知角色偶发单帧识别失败只写调试日志。离线验证未启动或操控游戏。\n'
                'V1.26.00：新增 Qingxiao（清宵）角色支持：通过 port_upstream_character 固定上游提交并生成只读审计报告，接入清宵战斗、达妮娅/莫宁联动与治疗角色满协奏切出后 16 秒锁；四个视觉标签及角色资源支持 1080P/1440P 离线深渊识别。全部验证均未启动或操控游戏。\n'
                'V1.25.00：加固多账号每日任务稳定性：绑定已验证账号后同步每日方案，梦魇传送与 F2 开书增加状态等待和恢复重试，梦魇失败不再误记账号今日完成；爱弥斯长动作增加超时及鼠标释放保护，战斗脱靶增加短观察窗，体力记账正确区分当前与备用体力。\n'
                'V1.24.00：自动深渊扫描三塔后自动进入残响之塔首个可挑战关卡，精确点击挑战开始与快速编队，自动截取并验证两屏角色列表；复用角色库识别头像、体力和等级，只显示体力大于0且等级大于60的角色，仍不会选择角色或进入战斗。\n'
                'V1.23.03：自动深渊在周期挑战页先明确点击左侧“逆境深塔”卡片，再只在中间内容区确认“深境区”并点击其右侧前往；不再将左侧副标题误作深境区目标。\n'
                'V1.23.02：修复自动深渊将左栏“敌迹探寻”误判为周期挑战：周期挑战图标改用去背景的灰色/金色双状态边缘模板，在整个导航栏内识别，不依赖固定上下位置；点击后仍须 OCR 确认“周期挑战”。\n'
                'V1.23.01：测试功能新增“自动深渊：深塔关卡扫描”；从 F2 周期挑战进入逆境深塔，逐座识别四个关卡的已完成、可挑战或未解锁状态。严格止步于扫描，不进入编队、不选择角色、不点击挑战开始，也不调用自动战斗。\n'
                'V1.23.00：剥离已放弃的 Android/MuMu 实验：相关源码、Agent、Nemu IPC、预检脚本、资源和测试已从 PC 正式程序及更新包移除，并在仓库外完整归档；WGC、Foreground BitBlt、SendInput、点击连接和账号切换流程均保持不变。\n'
                'V1.22.08：修复账号方案联动后的 Qt 原生崩溃：任务工作线程不再直接刷新任务卡，GUI 刷新入口统一拒绝非主线程调用，避免 QLabel/QTextDocument 布局竞态导致访问违例。\n'
                'V1.22.07：修复游戏登录页被误判为启动器：账号身份与精确“登录”按钮组合优先确认可操作登录页，KURO、公告、修复和产品版本不再作为启动器专属特征；真正启动器候选还需“开始游戏”且属于不同前台进程。\n'
                'V1.22.06：修复账号切换 OCR 全角字符兼容：账号身份统一执行 Unicode NFKC 归一化；KURO 公告等启动器强特征优先于普通登录文字判断，检测到启动器时明确停止，不再误报账号下拉框超时。\n'
                'V1.22.05：加速多账号退登观察：设置页、电源按钮和世界状态优先复用同一张整屏 BitBlt 帧进行模板识别，“返回登录”只 OCR 右侧按钮区域；只有这些状态均未命中才执行登录整屏 OCR，并移除 ESC 与电源点击后重复的第二个 1 秒等待。\n'
                'V1.22.04：修复整显示器 BitBlt 返回 BGRA 四通道图像导致 OCR 在打开账号下拉列表前异常；现在统一转换为三通道 BGR，整屏坐标、前台校验和 SendInput 路径保持不变。\n'
                'V1.22.03：账号切换期间强制鸣潮前台并用 Foreground BitBlt 捕获游戏所在整块显示器；组合登录窗口和 ComboLBox 统一从最终桌面图像识别，坐标使用显示器原点；失败时不回退 WGC，所有点击继续使用校验后的 SendInput，并保留“点击连接”精确识别，状态与日志只显示 A3/A4 等短名。\n'
                'V1.22.02：退登流程每进入主界面、设置页或确认框的新状态都会续期 45 秒，适配慢速前台捕获和 OCR；设置页优先识别脱敏电源图标模板；账号列表允许同进程 ComboLBox 安全命中，状态窗固定显示 A3/A4 等账号短名。\n'
                'V1.22.01：修复当前鸣潮设置页仅显示电源图标时无法退登；同帧确认设置页后安全点击左下电源图标，并只识别点击确认框右侧“返回登录”，避免误点“退出游戏”。\n'
                'V1.22.00：退登状态机优先使用任务级前台桌面捕获并保留 WGC 后备；新增轻量置顶任务状态窗，显示当前账号、阶段、详情、耗时、告警和错误，独立登录窗口继续使用各自 HWND BitBlt。\n'
                'V1.21.00：PC 登录、退登和账号切换鼠标点击统一使用校验后的 Win32 SendInput；主窗口继续使用 WGC，独立登录窗口及 ComboBox/ComboLBox 使用各自 HWND 的 BitBlt 与实时坐标，投递和界面确认分离，伪 Win32 测试不会操作游戏。\n'
                'V1.20.02（验证中）：账号选择后稳定核验扩展为 20 秒，保留连续两次一致的安全条件，适配登录器慢速 OCR 与窗口切换。\n'
                'V1.20.01（候选修复）：修复账号下拉框当前已选目标被重复点击后无法收起，并将账号切换任务状态限制为 A3/A4 等短名，禁止在 UI 显示手机号、备用名或特征码。\n'
                'V1.20.00（候选基线）：综合修复账号配置发布、启动门禁、日志脱敏、五页导航和个人发布流水线。\n'
                'V1.19.12：修复多账号每日任务从游戏世界启动时误等登录界面：账号切换入口会在队伍 HUD 明确可见时先安全退登；异常、停止和正常完成都会释放运行状态，失败后可立即重试。修复配置备份错误排除发布目录内嵌套 manifest.json 导致的校验失败。\n'
                'V1.19.02：每日任务的凝素领域选择改为带名称的下拉框；第 1～4 项显示陨翼云渊-武器及技能材料：迅刀、静灭云渊-武器及技能材料：音感仪、裂斩云渊-武器及技能材料：长刃、碎蚀云渊-武器及技能材料：臂铠，内部仍保存原 F2 整数序号，未命名项目暂保留序号占位。\n'
                'V1.19.01：修复五个主页面分区嵌入视图沿用旧滚动区尺寸提示，导致账号配置等内容只占左侧、右侧大面积空白；重新嵌入前解除 QScrollArea 所有权并统一使用水平扩展策略，配置表单和列表跟随可用宽度铺满。\n'
                'V1.19.00：普通账号编辑锁定七类身份字段，新增校验当前身份、冲突检查、备份和 CAS 发布的独立重新绑定流程；账号页身份字段只读，身份变更不混入任务配置保存；本机备份使用 Windows DPAPI，完整账号快照写入 .dpapi 旁车文件，备份根目录默认启用当前用户 ACL，恢复拒绝路径遍历和符号链接逃逸；运行时统一读取 active bundle 图存储，并新增账号选择、不可变序列快照、停止协调、统一脱敏、账号筛选、序列成员和配置方案平铺显示。\n'
                'V1.18.00：账号配置与序列配置发布后实时联动刷新兄弟面板、每日任务、多账号任务和账号切换测试；运行中的任务保持冻结快照，变更从下一次运行生效。\n'
                'V1.18.00：增加 MuMu V6.5.5 阶段01只读预检，自动检测实际鸣潮包名、设备属性、Nemu IPC 截图和 Combat Agent 心跳；阶段01不发送游戏输入，后续 Android 队伍为 Augusta、Iuno、ShoreKeeper。任务页和游戏覆盖层不显示运行日志，日志仅写入文件。\n'
                'V1.17.02：每日任务和多账号每日任务正式通过账号仓库读取 active 账号快照，避免继续使用启动时旧内存快照。\n'
                'V1.17.01：任务运行时优先读取已校验的 active 账号快照；快照损坏时安全停止，不回退到可能半写入的总配置。\n'
                'V1.17.00：增加独立账号文件、带星号脱敏手机号优先匹配、U…A 备用识别名和暂不启用的游戏内特征码字段；发布快照使用原子指针。\n'
                'V1.16.01：修复开发版缺少 account_master_config.json 时账号配置页初始化直接退出的问题；现在保留窗口并进入可恢复安全状态。\n'
                'V1.16.00：固定浅色 Codex 风格；左侧收敛为通用设置、账号设置、任务、活动、测试功能五页，页面内容直接平铺，账号/活动页移除内部标签页并统一区块、设置行、任务日志和辅助对话框样式。\n'
                'V1.15.01：修复账号设置中新建序列或调整成员后每日任务/多账号每日任务仍读取旧快照的问题；任务页隐藏窗口尺寸内部诊断日志。\n'
                'V1.15.00：账号配置页新增所属序列复选框；保存账号时可直接加入或移出多个序列，序列成员更新与账号配置共用修订检查和原子发布。A1→序列2仅作为操作示例，不自动修改现有账号。\n'
                'V1.14.03：重新区分账号配置与序列配置操作；账号页明确“删除当前账号”，序列页明确“删除当前序列”，上下移动明确为“上移账号/下移账号”，减少误删对象的风险。\n'
                'V1.14.02：账号配置页的体力用途禁止鼠标滚轮切换，无音区、凝素领域和模拟领域只能展开下拉菜单后点击选择，避免滚动页面时误改账号配置。\n'
                'V1.14.01：账号配置结构化表单补全中文显示；副本、材料和梦魇目标使用中文标签，保存时仍写回原英文内部值，不改变每日任务识别逻辑。\n'
                'V1.14.00：主界面整合为通用设置、账号设置、任务、活动、测试功能五个入口；通用设置在同一页面展示监控与启动、实时触发、游戏快捷键和全局行为。新增中文结构化账号表单与二次确认级联删除，修复序列确认删除无反馈，并将悲鸣行动：无音危机归入常驻活动、账号切换测试归入多账号每日任务测试。\n'
                'V1.13.00：新增统一账号身份解析、安全账号配置页和独立序列管理页；账号修改使用草稿、脱敏差异、短名确认、账号级备份及修订冲突检查。正式多账号任务与切号测试共用不可变运行快照。完成每账号独立目录的只读迁移评估，当前结论为 NO-GO，不改动真实数据。\n'
                'V1.08.01：修复启动时完整性对话框阻塞启动器握手的问题。主窗口先完成显示并通知启动器，再延迟执行配置审查；审查通过前不会启动命令行任务、自动任务或 .okscript，失败时保持安全模式，并防止重复启动回调。\n'
                'V1.08.00：账号配置导入导出升级为可验证 v2 配置包，总配置、运行记录和偏好分区保存；首次锚定及已锚定空序列可从旧多账号配置恢复全部序列。每日/事务备份增加 SHA-256 清单、回滚和限额清理。正式多账号任务与测试共用唯一切换入口，失败时保留最近 60 秒并标注实际点击位置，按 7 天/20 次/500MB 清理。\n'
                'V1.07.00：新增旧版本账号配置首次锚定：总配置缺失时，用户查看说明并明确确认后，可将合法的当前账号配置转换为 schema v1 总配置；复用或生成稳定 UUID，保留任务值、序列顺序、完成记录和运行进度。迁移使用原子写入、后验复检及三文件回滚，身份歧义或损坏数据保持安全模式；新增运行端 AI 详细说明。\n'
                'V1.06.01：修复账号完整性对话框恢复按钮无法使用的问题；知晓差异后可直接“使用总配置覆盖全部账号配置”，一次完成指纹确认与账号配置恢复，保留全局设置、完成记录和运行进度，失败时工作配置与运行状态一并回滚。\n'
                'V1.06.00：新增只读账号总配置与完整性门禁：启动、任务开始及每次退登/选号前进行语义复检；异常配置留证并进入安全模式，须用户确认后才能按总配置恢复。账号专属任务配置改为只读快照，完成记录与多账号进度按稳定 profile_id 原子保存；兼容 A1/A3/A4、备用名、U 账号及掩码手机号，并拒绝歧义身份。\n'
                'V1.05.01：修复登录按钮 PostMessage 投递后界面不跳转的问题；后续尝试会重新 OCR 当前登录按钮并改用系统鼠标点击。退登流程改为按确认框、设置页、主界面和加载态分别处理，不再误按 ESC 关闭确认框或因 OCR 轮询次数提前超时。\n'
                'V1.05.00：重构多账号切换状态机：主界面启动先退登识别真实账号；退登、选号和登录点击均校验结果并有限重试；备用名与旧 Account Name 全链路生效，重复身份安全停止；修复停止传播、回登通知及旧测试脚本分叉。\n'
                'V1.04.03：账号切换改为优先捕获 ComboLBox 下拉列表并按目标 OCR 框进行系统鼠标点击，兼容列表向上/向下展开和当前账号重复项；修复停止请求被抗闪烁等待吞掉后任务仍继续的问题。\n'
                'V1.04.02：修复账号点击异步投递丢失（单帧 OCR 同时匹配掩码/U/备用名；区分点击投递与稳定确认；刷新句柄后重投，最后以目标 OCR 框验证的系统屏幕点击兜底），正式多账号任务和账号切换测试共用流程。\n'
                'V1.04.1：修复登录器切换账号时的界面闪烁误判（列表收起、空 OCR、旧账号帧均等待稳定；目标账号连续识别两次后确认），正式多账号任务与账号切换测试共用稳定检测与重试流程。\n'
                '\n'
                'V1.04.0：账号切换可靠性与连续测试（账号不一致时重新展开并重选目标账号，登录前再次核对；新增 A1→A3→A4 连续切换模式，仅模拟每日任务完成后的切换部分；精确短名解析防 A1/A10 误配，并覆盖备用名与手机号掩码）\n'
                '\n'
                'V1.03.74：修复「点击下拉框无效果」误判（列表已展开仍报 no effect 卡死；展开态与收起态分开判定，点击后等待列表展开再选账号）；多账号↔每日任务方案真正联动（此前只改了本任务自身配置，DailyTask 执行/界面仍用旧方案，现调用 switch_profile 同步 DailyTask 配置并刷新界面）\n'
                '\n'
                'V1.03.73：登录界面完整对话框支持（#32770 帧识别+选账号+点登录，屏幕坐标点击；撤销 WGC 捕获对话框导致的失败）；U 扫码账号支持\n'
                '\n'
                'V1.03.72：修复登录界面捕获（登录账号下拉框在独立 #32770 窗口，捕获目标优先 top_hwnd）；登录识别支持 U 扫码账号；退过头到启动器检测\n'
                '\n'
                'V1.03.71：多账号每日任务抗闪烁加固（登录界面等待容忍暗屏/窗口闪烁、窗口恢复、分阶段确认）；主界面分支每日任务配置联动当前执行账号\n'
                '\n'
                'V1.03.70：深度审查修复（重启 NameError / PowerShell 注入防护 / 验证脚本防数据覆盖 / .okscript 白名单 / 鼠标轮询降频 / 正则转义 / GDI 释放 / 日志脱敏等）；删除一次性工具脚本\n'
                '\n'
                'V1.03.69：修复切换序列后配置方案切换失效（下拉 tr_dict 未同步导致写入 None）；启动同步加 config 守卫\n'
                '\n'
                'V1.03.68：修复配置方案切换不触发（Daily Profile 为空时 old=None 短路，改为 old!=value 强制加载新方案）\n'
                '\n'
                'V1.03.67：导入账号配置不再保存旧方案（防当前污染配置覆盖导入的干净数据）\n'
                '\n'
                'V1.03.66：导入账号配置时过滤空/null 异常方案（防导入污染数据）\n'
                '\n'
                'V1.03.65：修复方案数据污染（下拉空白被当方案名创建 null 方案污染识别名），过滤空/null 键；提供数据修复工具\n'
                '\n'
                'V1.03.64：配置方案下拉防空白（当前方案不在选项时显示第一项，修复 B2 偶发不显示）\n'
                '\n'
                'V1.03.63：下拉信号恢复防遗留（blockSignals 用 try/finally）+ 切换方案调试日志（排查选A出B）\n'
                '\n'
                'V1.03.62：修复启动时配置方案下拉显示全部账号（序列过滤在卡片构建前生效）\n'
                '\n'
                'V1.03.61：修复方案序列默认值（默认序列1，不再显示全部账号）；多账号联动防污染（目标方案不存在时不创建）\n'
                '\n'
                'V1.03.60：更新日志补全 v1.03.56~1.03.59\n'
                '\n'
                'V1.03.59：多账号↔每日任务联动（激活方案跟随执行账号、当前执行账号动态更新，下次从断点处继续）\n'
                '\n'
                'V1.03.58：修复监控录像残像聚落段（先 esc 回主界面 + 开首领书再点残像聚落入口）\n'
                '\n'
                'V1.03.57：失败必留档（主界面第一轮保存断点、账号选择失败/防误登时强制截图）\n'
                '\n'
                'V1.03.56：修复多账号选账号崩溃（点击结果 True 被当账号名，bool.lower 报错）\n'
                '\n'
                'V1.03.54：今日完成跳过（单任务/多账号统一，今日已跑过的账号不重复执行）\n'
                '\n'
                'V1.03.53：多账号新增「当前执行账号」（选 A3 从 A3 开始，A10 完成后绕回 A1-A2）\n'
                '\n'
                'V1.03.52：文件按类别归并（诊断日志并入 logs/实验性日志、账号导出进数据仓库）\n'
                '\n'
                'V1.03.51：多账号第一轮修复（登录界面启动时选下一个未完成账号，防重跑/防误登）\n'
                '\n'
                'V1.03.50：多账号登录前核对账号（显示账号与目标不一致则中止登录，防误登）\n'
                '\n'
                'V1.03.49：布局更新（监控页/运行日志移到任务页/更新日志+作者的话并入关于页/录像选项改战令）\n'
                '\n'
                'V1.03.48：配置备份纳入数据仓库（ok仓库）\n'
                '\n'
                'V1.03.47：数据仓库文件夹（统一存储：监控录像/配置备份/账号数据）\n'
                '\n'
                'V1.03.46：自动登录默认关闭；多账号切换排查日志\n'
                '\n'
                'V1.03.45：录像保存位置改为全局设置\n'
                '\n'
                'V1.03.44：录像保存位置可选（保存到 所选文件夹\\okww监控室）\n'
                '\n'
                'V1.03.43：任务运行日志常驻 + 详细中文阶段日志\n'
                '\n'
                'V1.03.42：更新日志同步（Vx.xx.xx：格式统一）\n'
                '\n'
                'V1.03.41：新增原版 okww 更新检测（启动后台检查，首页提醒）\n'
                '\n'
                'V1.03.40：序列命名改数字（A=序列1、B=序列2…）\n'
                '\n'
                'V1.03.39：多账号任务序列归属联动 + 管理序列按钮（增删/重命名）\n'
                '\n'
                'V1.03.38：序列归属数据（sequences）落地 + 导出/导入包含归属\n'
                '\n'
                'V1.03.37：方案两级选择修正（选序列后账号配置即时联动）\n'
                '\n'
                'V1.03.36：每日任务方案两级选择 + 导入备份扩展（多账号数据一同备份）\n'
                '\n'
                'V1.03.35：切换方案刷新安全版（修复白屏）\n'
                '\n'
                'V1.03.34：刷新改延迟重建（修复导入白屏）\n'
                '\n'
                'V1.03.33：导入/切换方案后立即刷新下拉（免重启）\n'
                '\n'
                'V1.03.32：修复 runtime+PYTHONPATH 下 pywin32 DLL 加载失败\n'
                '\n'
                'V1.03.31：单实例检查只匹配 python 进程（消除误拦）\n'
                '\n'
                'V1.03.30：启动异常捕获扩展到 OK 构造（可查日志不再静默）\n'
                '\n'
                'V1.03.29：单实例弹窗可选（结束旧实例重启/继续使用/取消）\n'
                '\n'
                'V1.03.28：修复 bat 启动双进程（runtime pythonw + PYTHONPATH）\n'
                '\n'
                'V1.03.27：bat 用 pythonw 启动 + 单实例拦截弹窗提示\n'
                '\n'
                'V1.03.26：单实例拦截打印匹配进程信息\n'
                '\n'
                'V1.03.25：修复单实例对相对路径漏拦\n'
                '\n'
                'V1.03.24：联网代理自愈（启动探测代理写入 git 配置）\n'
                '\n'
                'V1.03.23：诊断增强（设备标识原文 + leveldb 明细）\n'
                '\n'
                'V1.03.22：诊断日志移至「实验性日志」文件夹\n'
                '\n'
                'V1.03.21：新增使用端诊断功能（启动收集环境/登录器信息）\n'
                '\n'
                'V1.03.20：退出清理加强（连带清理孤儿 WebView）\n'
                '\n'
                'V1.03.19：布局调整（三卡片高度宽度、作者的话）\n'
                '\n'
                'V1.03.18：退出联动终止进程树（消除孤儿进程）\n'
                '\n'
                'V1.03.17：修复关闭窗口后进程残留（closeEvent 强制退出）\n'
                '\n'
                'V1.03.16：作者的话独立模块 + 缩小设置模块\n'
                '\n'
                'V1.03.15：更新日志加入作者的话\n'
                '\n'
                'V1.03.14：单实例保护 + 关闭窗口时联动结束启动器进程\n'
                '\n'
                'V1.03.13：完善发布版标题与更新日志\n'
                '\n'
                'V1.03.12：二维码/扫码登录识别、卡登录界面重试、自动退登防抖动\n'
                '\n'
                'V1.03.11：卡欢迎页重试、卡进游戏界面重试\n'
                '\n'
                'V1.03.10：优化码识别、卡登录界面重试\n'
                '\n'
                'V1.03.09：断点续跑、扫码账号识别\n'
                '\n'
                'V1.03.08：多账号每日任务上线\n'
                '\n'
                'V1.03.07：修复任务后录像页面（残像聚落改用首领书正确入口、大月卡改用左上角战令入口）\n'
                '\n'
                'V1.03.06：任务后录像（okww监控室）\n'
                '\n'
                'V1.03.05：每日任务内新增每周乐园检查\n'
                '\n'
                'V1.03.04：任务页布局调整\n'
                '\n'
                'V1.03.03：更新日志改为可滚动的历史记录（所有版本保留）\n'
                '\n'
                'V1.03.02：修复启动崩溃（QLabel 未导入、开关配置类型不存在）\n'
                '\n'
                'V1.03.01：多账号每日任务（断点续跑/账号序列/扫码账号识别）、'
                '序列切换重构（游戏登录缓存隔离）、界面全中文、配置自动备份、一键重启、运行日志常驻\n'
                '\n'
                'v1.02.01：版本显示功能上线（初始版本）'))
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(update_log_text)
            self.add_card(self.tr('更新日志'), widget)
        except Exception:
            pass

    def _add_author_card(self):
        try:
            author_text = QPlainTextEdit()
            author_text.setReadOnly(True)
            author_text.setMaximumHeight(225)
            author_text.setPlainText(self.tr(
                '如果有人不小心下载到了这个版本，请注意，这是okww的个人自用AI魔改版本，'
                '作者本身是个小白，没有任何计算机经验，此版本存在大量问题，上传github仅为了方便更新。\n'
                '本作品的原版是okww，点击上方的github链接应该就是，原作者留下的很多东西我都没改，赞助也是他的。\n'
                '如果你下定决心使用这个版本，有什么问题可以反馈，有需求也可以提，但是不一定看得到，我不太会看。\n'
                '此版本的核心是优化了多账号支持，但是做的并不好，多账号每日部分还在尝试。'))
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(author_text)
            self.add_card(self.tr('作者的话'), widget)
        except Exception:
            pass

    @staticmethod
    def _format_update_note(content):
        """升级说明统一格式：'内容；v1.03.41' → 'V1.03.41：内容'。"""
        try:
            import re
            m = re.search(r'；?\s*[vV]?(\d+\.\d+\.\d+)\s*$', content or '')
            if m:
                return f'V{m.group(1)}：{(content[:m.start()]).rstrip("； ")}'
        except Exception:
            pass
        return content

        projects = [
            {"name": self.tr("ok-py Automation Tool"), "url": "https://github.com/ok-oldking/ok-py"},
            {"name": self.tr("ok-script App Template"), "url": "https://github.com/ok-oldking/ok-script-app"},
            {"name": self.tr("Wuthering Waves"), "url": "https://github.com/ok-oldking/ok-wuthering-waves"},
            {"name": self.tr("Girls' Frontline 2"), "url": "https://github.com/ok-oldking/ok-gf2"},
            {"name": self.tr("Star Resonance"), "url": "https://github.com/Sanheiii/ok-star-resonance"},
            {"name": self.tr("Duet Night Abyss"), "url": "https://github.com/BnanZ0/ok-duet-night-abyss"},
            {"name": self.tr("Chaos Zero Nightmare"), "url": "https://github.com/baoxin1100/ok-kes"},
            {"name": self.tr("Onmyoji"), "url": "https://github.com/YunLiuZ/ok-Onmyoji"},
            {"name": self.tr("Arknights: Endfield"), "url": "https://github.com/AliceJump/ok-end-field"},
            {"name": self.tr("Neverness to Everness"), "url": "https://github.com/BnanZ0/ok-neverness-to-everness"},
        ]

        def normalize_url(url):
            return url.strip().lower().rstrip('/') if url else ""

        links = config.get('links') or {}
        current_github_norm = normalize_url(get_localized_app_config(links, 'github'))

        filtered_projects = [p for p in projects if normalize_url(p['url']) != current_github_norm]

        if filtered_projects:
            self.group = SettingCardGroup(self.tr("Other Projects"), self)
            
            self.group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            grid_widget = QWidget()
            grid_widget.setSizePolicy(grid_widget.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
            
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setHorizontalSpacing(12)
            grid_layout.setVerticalSpacing(12)
            grid_layout.setAlignment(Qt.AlignTop)

            for i, project in enumerate(filtered_projects):
                card = ProjectCard(project['name'], project['url'], grid_widget)
                grid_layout.addWidget(card, i // 2, i % 2)

            self.group.addSettingCard(grid_widget)
            self.group.setContentsMargins(0, 0, 0, 0)
            self.add_widget(self.group)

        if about := config.get('about'):
            about_label = BodyLabel()
            about_label.setText(about)
            about_label.setWordWrap(True)
            about_label.setOpenExternalLinks(True)
            about_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            about_label.setContentsMargins(0, 0, 0, 0)

            self.add_card(None, about_label)

        self.vBoxLayout.addStretch(1)

    def _startup_version_change_title(self, version_change):
        if version_change.action == "update":
            title = self.tr("Update success {from_version} -> {to_version}")
        elif version_change.action == "downgrade":
            title = self.tr("Downgrade success {from_version} -> {to_version}")
        else:
            return version_change.title
        return title.format(from_version=version_change.from_version, to_version=version_change.to_version)
