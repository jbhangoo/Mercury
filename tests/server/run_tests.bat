@echo off
setlocal
cd /d "%~dp0\..\.."
uv run pytest
exit /b %errorlevel%