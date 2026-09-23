"""Compatibility wrapper; the launcher lives in `atelierx.launcher` (`python -m atelierx.launcher`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from atelierx.launcher.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
