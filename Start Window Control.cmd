@echo off
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
  pythonw.exe -B "%~dp0launch_stdio.py" --helper-only
) else (
  "C:\Python313\pythonw.exe" -B "%~dp0launch_stdio.py" --helper-only
)
