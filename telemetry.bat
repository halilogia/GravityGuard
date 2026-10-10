@echo off
setlocal enabledelayedexpansion
title GravityGuard Telemetry & Security Dashboard

if not "%~1"=="" (
    python "%~dp0tools\telemetry_dashboard.py" %*
    goto end
)

:menu
cls
echo ============================================================================
echo           GRAVITYGUARD TELEMETRI, GUVENLIK VE DENETIM MERKEZI
echo ============================================================================
echo.
echo  [1] Genel Durum Paneli (All-Time Dashboard)
echo  [2] Haftalik Analiz ve Gecen Haftayla Karsilastirma (--weekly)
echo  [3] Aylik Analiz ve Gecen Ayla Karsilastirma (--monthly)
echo  [4] Tum Log Kaynaklarini Birlestir (Antigravity + Claude Code) (--all)
echo  [5] Kural Gelistirme ve Optimizasyon Onerileri (--candidates)
echo  [6] Haftalik Raporu Markdown Olarak Cikar (reports\weekly_digest.md)
echo  [7] Log Rotasyonu ve Arsivleme (--rotate)
echo  [8] Cikis
echo.
set /p opt="Seciminiz [1-8]: "

if "%opt%"=="1" python "%~dp0tools\telemetry_dashboard.py" & goto pause_done
if "%opt%"=="2" python "%~dp0tools\telemetry_dashboard.py" --weekly & goto pause_done
if "%opt%"=="3" python "%~dp0tools\telemetry_dashboard.py" --monthly & goto pause_done
if "%opt%"=="4" python "%~dp0tools\telemetry_dashboard.py" --all & goto pause_done
if "%opt%"=="5" python "%~dp0tools\telemetry_dashboard.py" --candidates & goto pause_done
if "%opt%"=="6" (
    if not exist "%~dp0reports" mkdir "%~dp0reports"
    python "%~dp0tools\telemetry_dashboard.py" --weekly --export-md "%~dp0reports\weekly_digest.md"
    echo.
    echo Rapor olusturuldu: "%~dp0reports\weekly_digest.md"
    goto pause_done
)
if "%opt%"=="7" python "%~dp0tools\telemetry_dashboard.py" --rotate & goto pause_done
if "%opt%"=="8" goto end
goto menu

:pause_done
echo.
pause
goto menu

:end
