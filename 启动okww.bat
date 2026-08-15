@echo off
setlocal
rem 以本文件所在目录为项目根（支持整个文件夹复制到任意位置）
cd /d "%~dp0"

rem ---- 管理员提权（PostMessage 需要与游戏同权限级别）----
rem 鸣潮游戏通常以管理员运行，okww 若普通权限，PostMessage 会被拒绝访问，
rem 导致 PC 端点击全部失败。检测非管理员时自动以管理员身份重启本脚本。
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限以操作游戏窗口，正在提权启动...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo   OK-WW 启动中...（管理员模式）
echo   请确保鸣潮游戏已经启动
echo   本窗口请保持打开，不要关闭
echo ========================================

rem ---- 自愈检查：修复 .venv 指向项目内 Python 运行时 ----
rem 整个文件夹复制到另一台电脑后，.venv 的 Python 路径会失效，
rem fix_venv.py 会把它重新指到本文件夹的 runtime\python。
if not exist "%~dp0runtime\python\python.exe" (
    echo.
    echo [错误] 缺少项目内 Python 运行时：runtime\python\python.exe
    echo 请确认复制的是完整文件夹（含 runtime 目录），或反馈此问题。
    echo.
    pause
    exit /b 1
)
"%~dp0runtime\python\python.exe" "%~dp0fix_venv.py"
if errorlevel 1 (
    echo.
    echo [错误] 运行环境自愈失败，请截图反馈。
    echo.
    pause
    exit /b 1
)

rem ---- 会话日志/截图：归档上一次的散落文件 + 清理过期会话 ----
"%~dp0runtime\python\python.exe" "%~dp0new_session.py"
"%~dp0runtime\python\python.exe" "%~dp0clean_session.py"

rem ---- 启动主程序 ----
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
set "code=%errorlevel%"
echo.
if not "%code%"=="0" (
    echo 程序异常退出（错误码 %code%），如果报错请截图发给我
)
pause
endlocal
