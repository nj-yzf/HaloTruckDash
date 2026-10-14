"""Write PyInstaller's Windows version resource from the shared release version."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halo_dashboard.version import VERSION, PRODUCT_NAME

parts = tuple(int(part) for part in VERSION.split('.')) + (0,)
text = f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'HaloTruckDash contributors'),
    StringStruct('FileDescription', {PRODUCT_NAME!r}),
    StringStruct('FileVersion', {VERSION!r}),
    StringStruct('InternalName', {PRODUCT_NAME!r}),
    StringStruct('OriginalFilename', 'HaloTruckDash.exe'),
    StringStruct('ProductName', {PRODUCT_NAME!r}),
    StringStruct('ProductVersion', {VERSION!r}),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 HaloTruckDash contributors')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
'''
target = Path(__file__).resolve().parents[1] / 'build' / 'windows-version-info.txt'
target.parent.mkdir(exist_ok=True)
target.write_text(text, encoding='utf-8')
print(target.name)
