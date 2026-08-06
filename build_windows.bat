@echo off
setlocal
cd /d %~dp0
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean GrantReviewAssistant.spec
echo.
echo Build finished. Open dist\GrantReviewAssistant and double-click GrantReviewAssistant.exe
pause
