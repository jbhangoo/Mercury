@echo off
setlocal
pushd "%~dp0"
rem Do not run in quiet mode so that the user can see the output of the test.
uv run python tests/database/check_database.py
set "test_exit_code=%errorlevel%"
popd
exit /b %test_exit_code%