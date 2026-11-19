@echo off
rem Chamado pelo Agendador de Tarefas (sem pause, para nao ficar esperando tecla).
cd /d "%~dp0"
python rodar.py
