@echo off
setlocal
pushd "%~dp0.."
docker build -t server-img -f server\Dockerfile server
set "result=%ERRORLEVEL%"
popd
exit /b %result%