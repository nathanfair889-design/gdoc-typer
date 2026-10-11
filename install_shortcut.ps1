# Adds "Google Doc Typer" to the Start Menu so it can be found by search.
# Run:  powershell -ExecutionPolicy Bypass -File install_shortcut.ps1
# Undo: delete the .lnk this prints, or pass -Uninstall

param([switch]$Uninstall)

$app = $PSScriptRoot
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) "Google Doc Typer.lnk"

if ($Uninstall) {
    if (Test-Path $lnk) { Remove-Item $lnk; "Removed $lnk" } else { "Nothing to remove." }
    return
}

# pythonw runs the app without a console window
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $guess = Join-Path (Split-Path (Get-Command python.exe).Source) "pythonw.exe"
    if (Test-Path $guess) { $pythonw = $guess }
}
if (-not $pythonw) { throw "Could not find pythonw.exe - is Python installed and on PATH?" }

$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath       = $pythonw
$s.Arguments        = '"' + (Join-Path $app "typer_app.py") + '"'
$s.WorkingDirectory = $app
$s.Description      = "Type text into Google Docs at a human pace, with realistic typos"
$icon = Join-Path $app "typer.ico"
if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
$s.Save()

"Installed: $lnk"
"Press Start and type 'Google Doc Typer'."
