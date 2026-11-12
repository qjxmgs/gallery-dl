$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $projectRoot 'gallery-dl GUI.lnk'))
$shortcut.TargetPath = Join-Path $projectRoot 'gui_start.bat'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'assets\gallery-dl.ico') + ',0'
$shortcut.Description = 'gallery-dl GUI'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output 'Created gallery-dl GUI.lnk in the project root.'
