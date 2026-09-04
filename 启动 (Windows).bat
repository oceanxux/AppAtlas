@echo off
rem App Store 价格全览 — Windows 双击启动
chcp 65001 >nul
cd /d "%~dp0"
python AppPriceTracker.py 2>nul || py AppPriceTracker.py
pause
