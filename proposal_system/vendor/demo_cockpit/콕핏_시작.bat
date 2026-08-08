@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   제안 자동화 시연 콕핏
echo   http://localhost:5700/  (브라우저로 열림)
echo   덱 11p의 "라이브 콕핏 열기" 링크도 여기로 연결됩니다.
echo   끄려면 이 창에서 Ctrl+C
echo ================================================
start "" "http://localhost:5700/"
node server.js
pause
