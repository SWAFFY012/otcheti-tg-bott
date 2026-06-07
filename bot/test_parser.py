import asyncio

from config import load_config
from parser import get_monthly_statistics
from report import build_text_report


async def main() -> None:
    config = load_config()
    data = await get_monthly_statistics(config.site)

    print(f"Tables found: {len(data.tables)}")
    print(f"Cards found: {len(data.cards)}")
    print(f"Last day found: {data.last_day or 'not found'}")

    if not data.tables and not data.cards:
        print("No data found. Check files in bot/debug_output to see what the parser loaded.")
        return

    print()
    print(build_text_report(data))


if __name__ == "__main__":
    asyncio.run(main())
