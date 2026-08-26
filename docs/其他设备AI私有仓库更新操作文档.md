# okww-custom GitHub 仓库：其他设备 AI 操作文档

适用仓库：<https://github.com/xihuojun2020-tech/okww-custom>

当前仓库目前为 **Public**，可匿名克隆和更新。若未来重新改为 Private，必须先由设备使用者完成 GitHub 身份认证；文档后面的认证流程仍保留备用。

## 给 AI 的安全规则

1. 不要要求用户把 PAT、密码或 SSH 私钥粘贴到聊天窗口、日志、代码或批处理文件中。
2. 认证信息只允许由用户在 Git Credential Manager、系统凭据管理器或 SSH 客户端提示中输入。
3. 不要执行 `git reset --hard`、`git clean -fd`、删除配置目录或覆盖账号数据。
4. 更新前先停止 okww，检查工作区状态，并备份用户配置。
5. 遇到冲突、凭据失败、未知远程地址或版本回退时停止操作，向用户报告，不要猜测处理。
6. `configs/`、`账号备份/`、运行状态和日志属于本机数据，不要提交或上传。

## 一、首次部署

### 1. 安装前置软件

- Windows 10/11
- Git for Windows（包含 Git Credential Manager）
- Python 3.12（项目优先使用自带或项目 `.venv`）
- 已安装并可正常启动的 okww 运行环境

验证 Git：

```powershell
git --version
git config --global credential.helper manager-core
```

### 2. 认证并克隆

执行：

```powershell
git clone https://github.com/xihuojun2020-tech/okww-custom.git
cd okww-custom
```

如果 Git Credential Manager 弹出登录窗口，使用有仓库访问权限的 GitHub 账号登录。

如果命令行要求输入凭据：

- Username：GitHub 用户名
- Password：Fine-grained PAT（只需要该仓库的 `Contents: Read` 权限）

不要把 PAT 写进 URL，例如不要使用：

```text
https://TOKEN@github.com/...
```

### 3. 初始化 Python 环境

进入项目目录后检查本地虚拟环境：

```powershell
if (Test-Path .\.venv\Scripts\python.exe) {
    .\.venv\Scripts\python.exe --version
} else {
    python --version
}
```

如果项目已有 `.venv`，不要删除或重建它。依赖安装应使用项目提供的依赖文件和本地解释器。

## 二、已有安装的安全更新流程

### 1. 停止程序

先关闭 okww UI、任务进程和启动脚本；确认没有任务仍在运行。

### 2. 备份本机数据

备份以下目录到本机安全位置，不要上传到 GitHub：

- `configs/`
- `账号备份/`
- `运行状态/`
- 用户自行保存的 `data/` 或运行目录

备份目录应放在项目目录之外，例如 `D:\游戏数据备份\设备名\日期\`。

### 3. 检查远程和工作区

```powershell
git remote -v
git status --short
git branch --show-current
```

远程地址必须是：

```text
https://github.com/xihuojun2020-tech/okww-custom.git
```

正常更新前，工作区应没有未提交的代码修改。若有修改，先把状态和文件清单报告给用户；不要擅自覆盖。

### 4. 拉取更新

```powershell
git fetch origin
git pull --ff-only origin master
```

`--ff-only` 用于防止 AI 自动创建未知合并提交。若提示无法 fast-forward，停止并报告。

### 5. 验证版本和提交

```powershell
git log -1 --oneline
git ls-remote origin refs/heads/master
Select-String -Path .\config.py -Pattern 'version\s*='
```

本地 HEAD 应与远程 `master` 的提交一致，`config.py` 中的产品版本应与 `更新日志.md` 和 About 页面一致。

## 三、更新后测试

优先使用项目本地 Python：

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness
& .\.venv\Scripts\python.exe -m unittest tests.TestAccountIdentityProtection tests.TestAccountRepositoryRuntime
& .\.venv\Scripts\python.exe -m unittest tests.TestConfigBackup tests.TestSecureBackup tests.TestConfigIntegrity
```

再运行确定性测试分组：

```powershell
& .\run_tests.ps1 -Group unit
& .\run_tests.ps1 -Group integration
& .\run_tests.ps1 -Group ui
& .\run_tests.ps1 -Group fault_injection
```

图像测试需要真实游戏窗口、OCR 资源和正确屏幕环境，不应在没有准备环境时强行执行。图像测试失败不得被 AI 自动归因于代码回归。

## 四、启动程序

测试通过后使用项目提供的启动脚本：

```powershell
& .\启动okww.bat
```

如果设备使用桌面快捷方式，确认快捷方式目标仍指向当前项目目录的 `启动okww.bat`，不要直接运行未知的旧副本。

启动后执行安全检查：

1. 确认 UI 能正常打开。
2. 检查账号配置页身份字段仍为只读。
3. 检查账号/序列列表和当前任务选项可以正常读取。
4. 先做预检，再启动真实任务。
5. 首次更新后不要立即进行不可逆的批量账号操作。

## 五、私有仓库认证故障（仅在仓库重新设为 Private 时适用）

### `Repository not found` 或 `403`

这通常不是仓库不存在，而是当前设备没有私有仓库权限。检查：

```powershell
git remote -v
git ls-remote origin refs/heads/master
```

请用户在 Git Credential Manager 中重新登录有权限的 GitHub 账号，或联系仓库所有者添加协作者/Deploy Key。不要改成公开仓库，也不要把令牌写入脚本。

### 凭据缓存错误

通过 Windows“凭据管理器”删除针对 `github.com` 的旧 Git 凭据，然后重新执行：

```powershell
git fetch origin
```

让 Git Credential Manager 再次弹出认证。不要在命令行历史中输入 PAT。

### 本地有未提交修改

AI 必须先报告：

- `git status --short` 输出
- 修改涉及哪些代码文件
- 是否包含用户数据

除非用户明确指定处理方案，否则不要 stash、reset、clean、checkout 或覆盖这些修改。

## 六、更新完成报告模板

其他设备 AI 完成后应报告：

```text
远程仓库：okww-custom（Public/Private，按当前 GitHub 状态填写）
当前分支：master
更新前提交：<sha>
更新后提交：<sha>
版本：<config.py 中的版本>
测试：unit/integration/ui/fault_injection 各自结果
本机配置：已备份/未备份（说明位置）
启动检查：通过/失败（附安全错误摘要）
```

报告中不得出现 PAT、密码、Cookie、完整手机号或其他账号凭据。
