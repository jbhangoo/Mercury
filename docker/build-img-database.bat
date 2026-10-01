@echo off
setlocal
pushd "%~dp0.."
docker build -t database-img -f database\Dockerfile database
set "result=%ERRORLEVEL%"
popd
exit /b %result%