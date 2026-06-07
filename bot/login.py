import asyncio

from playwright.async_api import async_playwright

from config import load_config


async def main() -> None:
    config = load_config()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(config.site.timeout_ms)

        await page.goto(config.site.url, wait_until="domcontentloaded")
        print("A browser window is open.")
        print("Log in to OfficeManager there, open the statistics page, then return here.")
        input("Press Enter after the page is open and you are logged in...")

        await context.storage_state(path=config.site.storage_state_path)
        print(f"Login session saved to {config.site.storage_state_path}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
