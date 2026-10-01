@echo off
setlocal
pushd "%~dp0"
uv run pytest tests/server
set "test_exit_code=%errorlevel%"
popd
exit /b %test_exit_code%