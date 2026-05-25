echo off
cd /d %~dp0
technyx_toolset lda_to_txt %*
if %errorlevel% NEQ 0 pause
