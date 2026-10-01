@echo off
setlocal
pushd "%~dp0client"
call npm test
set "test_exit_code=%errorlevel%"
popd
exit /b %test_exit_code%