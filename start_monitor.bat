@echo off
rem Start the TPS floating-window monitor silently (bonc pythonw, no console)
set "PYW=D:\miniconda3\envs\bonc\pythonw.exe"
if not exist "%PYW%" set "PYW=D:\miniconda3\envs\bonc\python.exe"
start "" "%PYW%" "%~dp0plugins\zcode-tps-overlay\overlay\tps_monitor.py"
