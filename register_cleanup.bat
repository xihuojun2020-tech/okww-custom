@echo off
rem ============================================================
rem  注册"每日清理 okww 会话日志/截图"的计划任务
rem  保留天数默认 7 天（可在下方 set 行修改）
rem  用法：双击本文件，按提示输入管理员密码确认即可
rem  移除：schtasks /delete /tn "OKWW_CleanSessions" /f
rem ============================================================
cd /d "%~dp0"

rem ---- 管理员权限检查（schtasks /create 需要管理员）----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限，正在提权启动...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "PYTHON=%~dp0runtime\python\python.exe"
set "SCRIPT=%~dp0clean_session.py"
set "KEEP_DAYS=7"

echo 注册计划任务: OKWW_CleanSessions (每日 03:00 运行, 保留 %KEEP_DAYS% 天)
schtasks /create /tn "OKWW_CleanSessions" /tr "\"%PYTHON%\" \"%SCRIPT%\"" /sc daily /st 03:00 /f
if errorlevel 1 (
    echo.
    echo [失败] 注册失败，可能需要管理员权限。
    echo 请右键本文件选择"以管理员身份运行"。
) else (
    echo.
    echo [成功] 已注册每日 03:00 自动清理。
    echo 如需立即清理一次，可运行: runtime\python\python.exe clean_session.py
)
pause
