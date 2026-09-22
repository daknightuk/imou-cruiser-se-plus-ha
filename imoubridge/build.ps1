$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildEnvironment = Join-Path $env:LOCALAPPDATA 'ImouBridgeBuild\.venv'
python -m venv $buildEnvironment
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
$buildPython = Join-Path $buildEnvironment 'Scripts\python.exe'
& $buildPython -m pip install -r requirements-app5.txt 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$wsdlPath = & $buildPython -c "from pathlib import Path; import onvif; print(Path(onvif.__file__).parent.parent / 'wsdl')"
if ($LASTEXITCODE -ne 0) { throw 'ONVIF resource lookup failed.' }
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name ImouBridge --collect-all onvif --collect-all zeep --collect-all paho --collect-all requests --add-data "${wsdlPath};wsdl" app5.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Write-Output 'Created dist\ImouBridge.exe'
