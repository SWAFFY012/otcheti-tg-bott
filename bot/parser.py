from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from config import SiteConfig


@dataclass
class ParsedReportData:
    source_url: str
    collected_at: datetime
    tables: list[dict]
    cards: list[dict[str, str]]
    last_day: dict[str, str] | None = None


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


async def _open_operational_days_tab(page: Page, config: SiteConfig) -> None:
    """Switch to the operational days tab when it is visible on the statistics page."""
    tab_text = config.data_selectors.get("operational_tab_text", "По дням (операционка)")

    try:
        tab = page.get_by_text(tab_text, exact=True)
        if await tab.count() > 0:
            await tab.first.click()
            await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
    except PlaywrightTimeoutError:
        return


async def _extract_tables(page: Page, selector: str) -> list[dict]:
    """Read every table into headers and row dictionaries."""
    tables = []
    table_locators = page.locator(selector)

    for table_index in range(await table_locators.count()):
        table = table_locators.nth(table_index)
        headers = _normalize_headers(
            await table.locator("thead th, tr:first-child th, tr:first-child td").evaluate_all(
                """cells => cells.flatMap(cell => {
                    const text = cell.innerText.trim();
                    const span = Number(cell.getAttribute('colspan') || 1);
                    return Array.from({ length: span }, () => text);
                })"""
            )
        )
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


def _normalize_headers(headers: list[str]) -> list[str]:
    normalized = []
    seen = {}

    for index, header in enumerate(headers):
        name = (header or f"column_{index + 1}").strip()
        if name == "Дата" and seen.get("Дата"):
            name = "День недели"
        elif name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        normalized.append(name)

    return normalized


def _cells_to_row(headers: list[str], cells: list[str]) -> dict[str, str]:
    if not headers:
        return {f"column_{index + 1}": value for index, value in enumerate(cells)}

    row = {}
    for index, value in enumerate(cells):
        header = headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}"
        row[header] = value
    return row


def _find_last_day_row(tables: list[dict]) -> dict[str, str] | None:
    """Find the last monthly row by the numeric day in the left table column."""
    best_day = -1
    best_row = None

    for table in tables:
        for row in table.get("rows", []):
            day_text = (row.get("Дата") or row.get("column_1") or "").strip()
            if not day_text.isdigit():
                continue

            day = int(day_text)
            if day > best_day:
                best_day = day
                best_row = row

    return best_row


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


async def _save_debug_artifacts(page: Page) -> None:
    debug_dir = Path(__file__).resolve().parent / "debug_output"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    await page.screenshot(path=debug_dir / f"monthly_statistics_{timestamp}.png", full_page=True)
    html = await page.content()
    (debug_dir / f"monthly_statistics_{timestamp}.html").write_text(html, encoding="utf-8")


async def get_monthly_statistics(config: SiteConfig) -> ParsedReportData:
    """Open OfficeManager, authorize if needed, wait for JavaScript data, and parse visible data."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.headless)
        context_options = {}
        if config.storage_state_path.exists():
            context_options["storage_state"] = str(config.storage_state_path)

        context = await browser.new_context(**context_options)
        page = await context.new_page()
        page.set_default_timeout(config.timeout_ms)

        try:
            await page.goto(config.url, wait_until="networkidle", timeout=config.timeout_ms)
            await _try_login(page, config)
            await _open_operational_days_tab(page, config)

            table_selector = config.data_selectors.get("tables", "table")
            card_selector = config.data_selectors.get("cards", "[data-testid], .card, .tile, .widget")

            try:
                await page.wait_for_selector(f"{table_selector}, {card_selector}", timeout=config.timeout_ms)
            except PlaywrightTimeoutError:
                # The report will still include a diagnostic sheet instead of failing silently.
                pass

            tables = await _extract_tables(page, table_selector)
            cards = await _extract_cards(page, card_selector)
            last_day = _find_last_day_row(tables)
            if not tables and not cards:
                await _save_debug_artifacts(page)

            await context.storage_state(path=config.storage_state_path)

            return ParsedReportData(
                source_url=config.url,
                collected_at=datetime.now(),
                tables=tables,
                cards=cards,
                last_day=last_day,
            )
        finally:
            await browser.close()
