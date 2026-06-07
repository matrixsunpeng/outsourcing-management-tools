@echo off
chcp 65001 >nul 2>&1
python "%~dp0run_budget_update.py"
if %errorlevel% neq 0 pause
