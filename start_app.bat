@echo off
rem 设置窗口标题
title AllValue 订单自动打印程序

rem --- 欢迎信息 ---
echo ======================================================
echo.
echo      正在启动 AllValue 订单自动打印程序...
echo.
echo      请不要关闭稍后弹出的黑色服务器窗口。
echo      关闭那个窗口即可停止本程序。
echo.
echo ======================================================

rem --- 激活 Conda 环境 ---
echo.
echo [步骤 1/3] 正在激活 Conda 环境
rem 使用 'call' 来确保激活后能继续执行此脚本
call conda activate allvalue_ui

rem 检查激活是否成功
if %errorlevel% neq 0 (
    echo.
    echo 错误：无法激活 Conda 环境 'allvalue_ui'。
    echo 请确认 Conda 已正确安装并已初始化。
    pause
    exit /b
)
echo 环境激活成功！

rem --- 启动 Flask 应用服务器 ---
echo.
echo [步骤 2/3] 正在后台启动 Flask 服务器...
rem 使用 'start' 命令在一个新的窗口中运行服务器，这样此脚本可以继续执行
start "Flask Server" cmd /k "python app.py"

rem --- 等待服务器启动 ---
echo.
echo [步骤 3/3] 等待 5 秒钟，让服务器有足够的时间启动...
rem timeout 命令会暂停脚本执行
timeout /t 5 /nobreak > nul

rem --- 自动打开浏览器 ---
echo.
echo 启动完成！正在打开浏览器访问应用主页...
start http://127.0.0.1:5000

rem --- 结束 ---
echo.
echo 程序已在后台运行。可以最小化此窗口，但不要关闭。