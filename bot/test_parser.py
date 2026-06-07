import asyncio

from config import load_config
from parser import get_monthly_statistics
from report import create_excel_report


async def main() -> None:
    config = load_config()
    data = await get_monthly_statistics(config.site)
    report_path = create_excel_report(data, config.report)

    print(f"Tables found: {len(data.tables)}")
    print(f"Cards found: {len(data.cards)}")
    print(f"Last day found: {data.last_day or 'not found'}")
    print(f"Excel report created: {report_path}")

    if not data.tables and not data.cards:
        print("No data found. Check files in bot/debug_output to see what the parser loaded.")


if __name__ == "__main__":
    asyncio.run(main())
