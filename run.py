"""Entry point: python run.py --help"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fdic_dwh.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
