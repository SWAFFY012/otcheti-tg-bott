import asyncio
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BOT_DIR = ROOT_DIR / "bot"

sys.path.insert(0, str(BOT_DIR))

from login import main  # noqa: E402


if __name__ == "__main__":
    asyncio.run(main())
