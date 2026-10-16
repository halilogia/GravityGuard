@echo off
chcp 65001 >nul
echo [GravityGuard] Otomatik IDE Guncelleyici Baslatiliyor...
python "%~dp0auto_update_ide.py"
pause
