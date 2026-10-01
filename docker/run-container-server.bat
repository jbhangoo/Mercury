@echo off
setlocal

docker network inspect mercury >nul 2>&1
if errorlevel 1 (
    docker network create mercury >nul
    if errorlevel 1 exit /b 1
)

docker container inspect server >nul 2>&1
if not errorlevel 1 (
    docker start server
    exit /b
)

docker run -d --rm --name server --network mercury --network-alias api -p 8000:8000 -e "DATABASE_URL=postgresql+psycopg://mercury:mercury_dev_password@database:5432/mercury" -e USE_DATABASE=1 -e DEBUG=0 -e CORS_ORIGINS=http://localhost:8080 server-img
exit /b %ERRORLEVEL%