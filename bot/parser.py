from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from config import SiteConfig


@dataclass
class ParsedReportData:
    source_url: str
    collected_at: datetime
    tables: list[dict]
    cards: list[dict[str, str]]


async def _locator_exists(page: Page, selector: str) -> bool:
    if not selector:
        return False
    return await page.locator(selector).count() > 0


async def _try_login(page: Page, config: SiteConfig) -> None:
    """Authorize when the page shows login inputs from config.json."""
    selectors = config.login_selectors
    username_selector = selectors.get("username", "")
    password_selector = selectors.get("password", "")
    submit_selector = selectors.get("submit", "")

    has_login_form = await _locator_exists(page, password_selector)
    if not has_login_form:
        return

    if not config.login or not config.password:
        raise RuntimeError("Site asks for authorization, but SITE_LOGIN/SITE_PASSWORD are not configured.")

    await page.locator(username_selector).first.fill(config.login)
    await page.locator(password_selector).first.fill(config.password)
    await page.locator(submit_selector).first.click()
    await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)


async def _extract_tables(page: Page, selector: str) -> list[dict]:
    """Read every table into headers and row dictionaries."""
    tables = []
    table_locators = page.locator(selector)

    for table_index in range(await table_locators.count()):
        table = table_locators.nth(table_index)
        headers = [
            (await header.inner_text()).strip()
            for header in await table.locator("thead th, tr:first-child th, tr:first-child td").all()
        ]
        rows = []

        row_locators = table.locator("tbody tr")
        if await row_locators.count() == 0:
            row_locators = table.locator("tr")

        for row_index in range(await row_locators.count()):
            cells = [
                (await cell.inner_text()).strip()
                for cell in await row_locators.nth(row_index).locator("th, td").all()
            ]
            if not cells:
                continue
            if headers and cells == headers:
                continue
            rows.append(_cells_to_row(headers, cells))

        if rows:
            tables.append({"name": f"table_{table_index + 1}", "rows": rows})

    return tables


def _cells_to_row(headers: list[str], cells: list[str]) -> dict[str, str]:
    if not headers:
        return {f"column_{index + 1}": value for index, value in enumerate(cells)}

    row = {}
    for index, value in enumerate(cells):
        header = headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}"
        row[header] = value
    return row


async def _extract_cards(page: Page, selector: str) -> list[dict[str, str]]:
    """Collect visible metric blocks for pages that render data as cards instead of tables."""
    cards = []
    card_locators = page.locator(selector)

    for index in range(await card_locators.count()):
        text = (await card_locators.nth(index).inner_text()).strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        cards.append({"title": lines[0], "value": " | ".join(lines[1:])})

    return cards


async def get_monthly_statistics(config: SiteConfig) -> ParsedReportData:
    """Open OfficeManager, authorize if needed, wait for JavaScript data, and parse visible data."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.headless)
        page = await browser.new_page()
        page.set_default_timeout(config.timeout_ms)

        try:
            await page.goto(config.url, wait_until="networkidle", timeout=config.timeout_ms)
            await _try_login(page, config)

            table_selector = config.data_selectors.get("tables", "table")
            card_selector = config.data_selectors.get("cards", "[data-testid], .card, .tile, .widget")

            try:
                await page.wait_for_selector(f"{table_selector}, {card_selector}", timeout=config.timeout_ms)
            except PlaywrightTimeoutError:
                # The report will still include a diagnostic sheet instead of failing silently.
                pass

            tables = await _extract_tables(page, table_selector)
            cards = await _extract_cards(page, card_selector)
            return ParsedReportData(
                source_url=config.url,
                collected_at=datetime.now(),
                tables=tables,
                cards=cards,
            )
        finally:
            await browser.close()
