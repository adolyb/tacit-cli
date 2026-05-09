@echo off
if not exist ".venv\Scripts\activate.bat" (
  echo .venv not found. Run setup_env.bat first.
  exit /b 1
)
call ".venv\Scripts\activate.bat"
