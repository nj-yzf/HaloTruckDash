$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$releaseVersion = & .\.venv\Scripts\python.exe -c 'from halo_dashboard.version import VERSION; print(VERSION)'
if ($LASTEXITCODE -ne 0 -or $releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version' }
$releaseDirectory = Join-Path 'dist' "v$releaseVersion"
$releaseArchive = Join-Path 'dist' "HaloTruckDash-v$releaseVersion-win-x64.zip"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
foreach ($check in @('grid_ui_verify', 'catalog_ui_verify', 'ats_ui_verify', 'main_ui_verify', 'hardware_ui_verify')) {
    & .\.venv\Scripts\python.exe "tools/checks/$check.py"
    if ($LASTEXITCODE -ne 0) { throw "$check failed" }
}
& .\.venv\Scripts\python.exe tools/write_version_info.py
if ($LASTEXITCODE -ne 0) { throw 'Windows version resource failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name HaloTruckDash --distpath $releaseDirectory --specpath build --workpath build/pyinstaller --icon "$PSScriptRoot/assets/HaloTruckDash.ico" --version-file "$PSScriptRoot/build/windows-version-info.txt" --add-data "$PSScriptRoot/assets;assets" main.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
foreach ($document in @('README.md','LICENSE','THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath $document -Destination "$releaseDirectory/$document" -Force
}
New-Item -ItemType Directory -Path "$releaseDirectory/licenses", "$releaseDirectory/docs" -Force | Out-Null
Get-ChildItem -LiteralPath assets/licenses | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination "$releaseDirectory/licenses" -Recurse -Force }
Copy-Item -LiteralPath docs/COMPATIBILITY.md -Destination "$releaseDirectory/docs/COMPATIBILITY.md" -Force
Copy-Item -LiteralPath docs/BUILDING.md -Destination "$releaseDirectory/docs/BUILDING.md" -Force
Compress-Archive -Path "$releaseDirectory/HaloTruckDash.exe", "$releaseDirectory/README.md", "$releaseDirectory/LICENSE", "$releaseDirectory/THIRD_PARTY_NOTICES.md", "$releaseDirectory/licenses", "$releaseDirectory/docs" -DestinationPath $releaseArchive -Force
$releaseHashes = Get-FileHash "$releaseDirectory/HaloTruckDash.exe", $releaseArchive -Algorithm SHA256
$releaseHashes | ForEach-Object { "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($_.Path))" } | Set-Content -LiteralPath "$releaseDirectory/SHA256SUMS.txt" -Encoding ascii
