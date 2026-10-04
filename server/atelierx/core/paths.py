"""Where everything lives inside the app folder (decision 0010)."""

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AppPaths:
    root: Path
    defaults: Path
    samples: Path
    web: Path

    @property
    def config(self):
        return self.root / 'config'

    @property
    def state(self):
        return self.root / 'state'

    @property
    def data(self):
        return self.root / 'data'

    @property
    def output(self):
        return self.root / 'output'

    @property
    def settings_file(self):
        return self.config / 'settings.json'

    @property
    def vault_file(self):
        return self.config / 'vault.json'

    @property
    def works(self):
        return self.data / 'works'

    @property
    def platforms(self):
        return self.data / 'platforms'

    @property
    def data_trash(self):
        return self.data / '.trash'

    @classmethod
    def for_dev(cls, root=None):
        """Development: the repository itself is the app folder (config/, data/ … are git-ignored)."""
        root = Path(root) if root else REPO_ROOT
        return cls(
            root=root,
            defaults=REPO_ROOT / 'defaults',
            samples=REPO_ROOT / 'samples',
            web=REPO_ROOT / 'web' / 'dist',
        )

    @classmethod
    def for_runtime(cls, root=None):
        """Keep portable user data beside the executable, resources inside its bundle."""
        if not getattr(sys, 'frozen', False):
            return cls.for_dev(root)
        resources = Path(sys._MEIPASS)
        return cls(
            root=Path(root).resolve() if root else Path(sys.executable).resolve().parent,
            defaults=resources / 'defaults',
            samples=resources / 'samples',
            web=resources / 'web' / 'dist',
        )
