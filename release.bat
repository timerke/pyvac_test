if exist build rd /s/q build
if exist dist rd /s/q dist
if exist release rd /s/q release
if exist venv rd /s/q venv

python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python -m pip install pyinstaller

venv\Scripts\pyinstaller main.py --clean --onefile ^
--add-data "gui\*;gui" ^
--hidden-import=PyQt5.sip ^
--icon gui\icon.ico

copy README.md dist

rename dist release
rename release\main.exe pyvac_test.exe

if exist build rd /s/q build
if exist dist rd /s/q dist
if exist venv rd /s/q venv
if exist main.spec del main.spec

pause