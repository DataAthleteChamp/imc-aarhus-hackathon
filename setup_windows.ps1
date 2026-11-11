# Hackathon setup for Windows: installs uv, Python 3.12 and the dependencies into .\.venv (no admin needed)
# Run in PowerShell from this folder:
#   powershell -ExecutionPolicy Bypass -File setup_windows.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (Python installer)...'
    powershell -ExecutionPolicy Bypass -c 'irm https://astral.sh/uv/install.ps1 | iex'
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host 'Creating .venv with Python 3.12...'
uv venv --python 3.12 --allow-existing .venv
if ($LASTEXITCODE -ne 0) { throw 'uv venv failed' }
uv pip install --python .venv -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Write-Host 'Checking...'
& .\.venv\Scripts\python.exe -c "import requests, sseclient, pandas, models, base_bot; print('All good:', __import__('sys').version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw 'check failed' }

Write-Host ''
Write-Host 'Done. Start each new terminal with:   .\.venv\Scripts\Activate.ps1'
Write-Host '  (if that is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)'
Write-Host 'Then run e.g.:                       python energi_snippet.py'
