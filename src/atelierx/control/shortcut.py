"""Windows login shortcut (user Startup folder) for the control panel; created only on explicit request."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import procs

SHORTCUT_NAME = "AtelierX Control Panel.lnk"


def default_startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


class StartupShortcut:
    def __init__(self, repo: Path, startup_dir=None):
        self.repo = Path(repo)
        self.directory = Path(startup_dir) if startup_dir else default_startup_dir()
        self.path = self.directory / SHORTCUT_NAME
        self.target = self.repo / "scripts" / "start_control_panel.bat"

    def exists(self) -> bool:
        return self.path.is_file()

    def create(self) -> None:
        if not self.target.is_file():
            raise FileNotFoundError("scripts/start_control_panel.bat가 없습니다.")
        self.directory.mkdir(parents=True, exist_ok=True)
        # Paths travel via environment variables so no quoting of user paths is needed inside the script.
        script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AX_LNK); $s.TargetPath=$env:AX_TARGET; "
                  "$s.WorkingDirectory=$env:AX_WORKDIR; $s.WindowStyle=7; $s.Description='AtelierX 로컬 운영 제어판'; $s.Save()")
        env = dict(os.environ, AX_LNK=str(self.path), AX_TARGET=str(self.target), AX_WORKDIR=str(self.repo))
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                                capture_output=True, timeout=30, creationflags=procs.NO_WINDOW)
        if result.returncode != 0 or not self.exists():
            raise RuntimeError("시작프로그램 바로가기를 만들지 못했습니다.")

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
