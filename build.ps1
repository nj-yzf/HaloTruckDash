$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$releaseVersion = & .\.venv\Scripts\python.exe -c 'from halo_dashboard.version import VERSION; print(VERSION)'
if ($LASTEXITCODE -ne 0 -or $releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version' }
$releaseDirectory = Join-Path 'dist' "v$releaseVersion"
$releaseArchive = Join-Path 'dist' "HaloTruckDash-v$releaseVersion.zip"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
foreach ($check in @('grid_ui_verify', 'catalog_ui_verify', 'ats_ui_verify', 'main_ui_verify', 'update_ui_verify')) {
    & .\.venv\Scripts\python.exe "research/$check.py"
    if ($LASTEXITCODE -ne 0) { throw "$check failed" }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name HaloTruckDash --distpath $releaseDirectory --add-data 'assets;assets' main.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath README.md -Destination "$releaseDirectory/README.md" -Force
Copy-Item -LiteralPath THIRD_PARTY_NOTICES.md -Destination "$releaseDirectory/THIRD_PARTY_NOTICES.md" -Force
New-Item -ItemType Directory -Path "$releaseDirectory/licenses" -Force | Out-Null
Get-ChildItem -LiteralPath assets/licenses | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination "$releaseDirectory/licenses" -Recurse -Force }
Compress-Archive -Path "$releaseDirectory/HaloTruckDash.exe", "$releaseDirectory/README.md", "$releaseDirectory/THIRD_PARTY_NOTICES.md", "$releaseDirectory/licenses" -DestinationPath $releaseArchive -Force
& .\.venv\Scripts\python.exe tools/make_update_manifest.py --archive $releaseArchive --output dist/latest.json --notes '新增在线检查更新、后台下载、进度与取消、SHA256及ZIP校验；支持配置HTTPS更新源和启动时自动检查。'
if ($LASTEXITCODE -ne 0) { throw 'Update manifest generation failed' }
Copy-Item -LiteralPath dist/latest.json -Destination "$releaseDirectory/latest.json" -Force
Get-FileHash "$releaseDirectory/HaloTruckDash.exe", $releaseArchive, dist/latest.json -Algorithm SHA256 | Select-Object Path,Hash | ConvertTo-Json | Set-Content "$releaseDirectory/SHA256.json" -Encoding utf8
