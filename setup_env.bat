@echo off
setlocal

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found on PATH. Install Python 3.10+ first.
  exit /b 1
)

if not exist ".venv\" (
  echo Creating venv at .venv\
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create venv.
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo Failed to activate venv.
  exit /b 1
)

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  exit /b 1
)

echo.
echo Setup complete. Run activate.bat to enter the venv next time.
endlocal
