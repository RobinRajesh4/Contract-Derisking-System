@echo off
cd /d C:\SEM5\internship\backend
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
