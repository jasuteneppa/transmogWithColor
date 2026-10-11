@echo off
setlocal
rem ======================================================================
rem  TransmogPalette: score new appearances after a patch.
rem
rem  Before running this (see UPDATING.md):
rem    1. In game, with Collections > Appearances open:
rem         /tmpalette capture journal           (every class), or
rem         /tmpalette capture journal class     (the class picked in the journal)
rem       (it only screenshots pages with something new on them)
rem    2. /reload in game (or log out), so the capture is written to disk.
rem
rem  Then double-click this file. It cuts the new tiles out of the
rem  screenshots, measures them, scores them with the saved model, and
rem  writes TransmogPalette\ColorScores.lua. /reload in game afterwards.
rem ======================================================================

set "TOOLS=%~dp0"
set "ADDON=%~dp0..\TransmogPalette"
set "PY=python"
set "MLPY=%USERPROFILE%\.venvs\transmog-ml\Scripts\python.exe"
set "BACKUP=%LOCALAPPDATA%\TransmogPalette\backups"

echo.
echo  TransmogPalette colour update
echo  ----------------------------
echo  Make sure you did /reload (or logged out) after the journal capture,
echo  or the new pages are not on disk yet.
echo.
pause

where %PY% >nul 2>nul || (echo ERROR: Python was not found on PATH. & goto :fail)
if not exist "%MLPY%" (echo ERROR: the ML Python environment is missing: %MLPY% & goto :fail)
if not exist "%TOOLS%color_model.npz" (echo ERROR: no saved model at %TOOLS%color_model.npz & goto :fail)
if not exist "%ADDON%\ColorScores.lua" (echo ERROR: %ADDON%\ColorScores.lua not found & goto :fail)

rem A copy of the current scores, so a bad run can be undone by copying it back.
if not exist "%BACKUP%" mkdir "%BACKUP%"
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "STAMP=%%t"
copy /y "%ADDON%\ColorScores.lua" "%BACKUP%\ColorScores_%STAMP%.lua" >nul || (echo ERROR: could not back up ColorScores.lua & goto :fail)
echo  Backed up the current scores to %BACKUP%\ColorScores_%STAMP%.lua
echo.

pushd "%TOOLS%"

echo [1/4] Cutting new tiles out of the screenshots...
%PY% journal_tiles.py || (echo ERROR: cutting tiles failed. & goto :failpop)
echo.

echo [2/4] Image model on the new tiles (the slow step if a patch added a lot)...
"%MLPY%" clip_embed.py || (echo ERROR: the image model step failed. & goto :failpop)
echo.

echo [3/4] Colour histograms for the new tiles...
%PY% journal_features.py || (echo ERROR: the histogram step failed. & goto :failpop)
echo.

echo [4/4] Scoring with the saved model...
%PY% build_scores.py --use-model || (echo ERROR: scoring failed - ColorScores.lua was not changed. & goto :failpop)

popd
echo.
echo  Done. /reload in game to use the new scores.
echo  If anything looks wrong, copy the backup above over
echo  %ADDON%\ColorScores.lua and /reload.
echo.
pause
exit /b 0

:failpop
popd
:fail
echo.
echo  The update stopped. ColorScores.lua is unchanged unless step 4 ran
echo  (a backup is in %BACKUP%).
echo.
pause
exit /b 1
