@echo off
title VideoCut
cd /d "%~dp0"
echo Iniciando VideoCut... (feche esta janela para encerrar)
if not exist ".venv\Scripts\python.exe" (
  echo Primeira execucao: instalando dependencias...
  uv sync --extra gpu || goto erro
)
".venv\Scripts\python.exe" -m videocut.cli ui || goto erro
exit /b 0
:erro
echo.
echo Algo deu errado. Veja a mensagem acima.
pause
