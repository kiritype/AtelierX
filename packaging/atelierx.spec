from pathlib import Path

root = Path(SPECPATH).parent
datas = []
for name in ('defaults', 'samples', 'comfy_nodes', 'trainer', 'web/dist'):
    for file in (root / name).rglob('*'):
        if not file.is_file() or any(p in ('__pycache__', '.git') for p in file.parts):
            continue
        if file.suffix in ('.pyc', '.pyo'):
            continue
        file.resolve().relative_to(root.resolve())
        datas.append((str(file), file.parent.relative_to(root).as_posix()))
datas += [(str(root / 'LICENSE'), '.')]
a = Analysis(
    [str(root / 'packaging' / 'windows_entry.py')],
    pathex=[str(root / 'server')], datas=datas,
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
                   'uvicorn.lifespan.on', 'webview.platforms.winforms', 'webview.platforms.edgechromium'],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AtelierX',
          debug=False, strip=False, upx=False, console=False,
          icon=str(root / 'packaging' / 'atelierx.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AtelierX')
