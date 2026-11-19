@echo off
rem Agenda a rotina diaria no Agendador de Tarefas do Windows (todo dia as 09:00).
rem Para mudar o horario: agendar.bat 18:30   |   Para remover: schtasks /delete /tn CortesGTA /f
cd /d "%~dp0"
set HORA=%1
if "%HORA%"=="" set HORA=09:00
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)"') do set PY=%%i
schtasks /create /tn CortesGTA /sc daily /st %HORA% /f /tr "cmd /c cd /d \"%~dp0\" && \"%PY%\" rodar.py"
echo Agendado para %HORA% todos os dias. O computador precisa estar ligado e com voce logado.
pause
