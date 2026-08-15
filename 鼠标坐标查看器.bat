@echo off
rem 鼠标坐标查看器：移动鼠标到目标位置 → 按空格记录 → q 退出
rem 记录会打印在本窗口，fallback 片段自动复制到剪贴板
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0mouse_pos.py"
pause
