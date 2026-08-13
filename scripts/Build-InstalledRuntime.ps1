param(
    [string]$Destination = "dist-installed"
)

$ErrorActionPreference = "Stop"
$destinationRoot = [IO.Path]::GetFullPath((Join-Path $PWD $Destination))
$runtimeRoot = Join-Path $destinationRoot "runtime"
$applicationRoot = Join-Path $destinationRoot "app"
$pythonRoot = (& python -c "import sys; print(sys.base_prefix)").Trim()

New-Item -ItemType Directory -Force -Path $runtimeRoot, $applicationRoot | Out-Null

foreach ($name in @("python.exe", "pythonw.exe", "python3.dll", "python312.dll")) {
    Copy-Item -LiteralPath (Join-Path $pythonRoot $name) -Destination $runtimeRoot -Force
}
Get-ChildItem -LiteralPath $pythonRoot -Filter "vcruntime*.dll" | Copy-Item -Destination $runtimeRoot -Force
Copy-Item -LiteralPath (Join-Path $pythonRoot "DLLs") -Destination $runtimeRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $pythonRoot "tcl") -Destination $runtimeRoot -Recurse -Force

$libraryRoot = Join-Path $runtimeRoot "Lib"
New-Item -ItemType Directory -Force -Path $libraryRoot | Out-Null
& robocopy (Join-Path $pythonRoot "Lib") $libraryRoot /E /XD site-packages __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Python standard-library copy failed with robocopy exit code $LASTEXITCODE."
}

& python -m pip install --no-compile --target (Join-Path $libraryRoot "site-packages") -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Application dependency installation failed."
}

& robocopy "app" $applicationRoot /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Application source copy failed with robocopy exit code $LASTEXITCODE."
}
New-Item -ItemType File -Force -Path (Join-Path $destinationRoot "installed.marker") | Out-Null

# Robocopy uses exit codes 1 through 7 for successful copy outcomes. Do not
# leak its final success code as the PowerShell script's process exit code.
exit 0
