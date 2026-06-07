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
    analytics: dict[str, str] | None = None


async def _locator_exists(page: Page, selector: str) -> bool:
    if not selector:
        return False
    return await page.locator(selector).count() > 0


async def _goto(page: Page, url: str, config: SiteConfig) -> None:
    """Navigate with retries; OfficeManager can keep background requests open for a long time."""
    last_error = None

    for _attempt in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=config.timeout_ms)
            await page.wait_for_timeout(2000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
            await page.wait_for_timeout(3000)

    raise last_error


async def _settle_after_click(page: Page, config: SiteConfig) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    await page.wait_for_timeout(1500)


async def _click_text(page: Page, text: str, config: SiteConfig) -> bool:
    """Click visible text using exact match first, then a softer contains-text fallback."""
    for locator in (
        page.get_by_text(text, exact=True),
        page.locator(f"text={text}"),
    ):
        if await locator.count() == 0:
            continue
        await locator.first.click()
        await _settle_after_click(page, config)
        return True
    return False


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
    await _settle_after_click(page, config)


async def _open_operational_days_tab(page: Page, config: SiteConfig) -> None:
    """Switch to the operational days tab when it is visible on the statistics page."""
    tab_text = config.data_selectors.get("operational_tab_text", "По дням (операционка)")

    try:
        tab = page.get_by_text(tab_text, exact=True)
        if await tab.count() > 0:
            await tab.first.click()
            await _settle_after_click(page, config)
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
            row = _cells_to_row(headers, cells)
            row["__row_index"] = str(row_index)
            row["__table_index"] = str(table_index)
            rows.append(row)

        if rows:
            tables.append({"name": f"table_{table_index + 1}", "rows": rows})

    return tables


async def _scroll_horizontal_areas(page: Page, ratio: float) -> None:
    """Scroll all horizontally scrollable containers to expose virtualized table columns."""
    await page.evaluate(
        """ratio => {
            for (const element of document.querySelectorAll('*')) {
                if (element.scrollWidth > element.clientWidth + 20) {
                    element.scrollLeft = (element.scrollWidth - element.clientWidth) * ratio;
                }
            }
        }""",
        ratio,
    )
    await page.wait_for_timeout(800)


async def _extract_tables_all_columns(page: Page, selector: str) -> list[dict]:
    """Extract table snapshots from left, middle, and right horizontal scroll positions."""
    tables = []

    for ratio in (0, 0.5, 1):
        await _scroll_horizontal_areas(page, ratio)
        tables.extend(await _extract_tables(page, selector))

    await _scroll_horizontal_areas(page, 0)
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


def _merge_related_rows(tables: list[dict], base_row: dict[str, str]) -> dict[str, str]:
    """Merge horizontally-scrolled snapshots that belong to the same visual row."""
    row_index = base_row.get("__row_index")
    merged = dict(base_row)

    if row_index is None:
        return merged

    for table in tables:
        for row in table.get("rows", []):
            if row.get("__row_index") != row_index:
                continue
            for key, value in row.items():
                if key.startswith("__") or value in ("", None):
                    continue
                if key not in merged or not merged[key]:
                    merged[key] = value

    return merged


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
                best_row = _merge_related_rows(tables, row)
            elif day == best_day and best_row is not None:
                best_row.update(_merge_related_rows(tables, row))

    return best_row


async def _open_guest_opinion(page: Page, config: SiteConfig) -> None:
    """Open Analytics -> Guest opinion using text labels visible in OfficeManager."""
    analytics_url = config.data_selectors.get(
        "analytics_url",
        "https://officemanager.dodois.io/OfficeManager/Analytics",
    )
    guest_opinion_text = config.data_selectors.get("guest_opinion_text", "Гостевое мнение")

    await _goto(page, analytics_url, config)

    print("Analytics: opening guest opinion...")
    await _click_text(page, guest_opinion_text, config)

    metrics_tab_text = config.data_selectors.get(
        "guest_metrics_tab_text",
        "Дизлайки и операционные метрики",
    )
    print("Analytics: opening dislikes and operational metrics...")
    await _click_text(page, metrics_tab_text, config)


async def _prepare_guest_opinion_table(page: Page, config: SiteConfig) -> None:
    """Set the analytics filters as closely as possible to the screen flow."""
    period_text = config.data_selectors.get("analytics_period_text", "Последние сутки")
    search_text = config.data_selectors.get("analytics_search_text", "химки")
    section_text = config.data_selectors.get("analytics_scores_section_text", "Оценки за весь период по кофейням")

    period = page.get_by_text(period_text, exact=True)
    if await period.count() > 0:
        await period.first.click()
        await page.keyboard.press("Escape")

    await page.mouse.wheel(0, 5000)

    section = page.get_by_text(section_text, exact=True)
    if await section.count() > 0:
        await section.first.scroll_into_view_if_needed()
    else:
        await page.mouse.wheel(0, 7000)

    search_candidates = [
        page.locator(f"text={section_text} >> xpath=following::input[1]"),
        page.get_by_placeholder("Поиск").last,
        page.locator("input").last,
    ]

    for search_input in search_candidates:
        if await search_input.count() == 0:
            continue
        try:
            print(f"Analytics: typing search '{search_text}'...")
            await search_input.fill(search_text)
            await page.wait_for_timeout(2500)
            if await page.get_by_text(search_text, exact=False).count() > 0:
                return
        except Exception:
            continue


def _find_row_by_text(tables: list[dict], needle: str) -> dict[str, str] | None:
    needle = needle.lower()
    for table in tables:
        for row in table.get("rows", []):
            if needle in " ".join(row.values()).lower():
                return _merge_related_rows(tables, row)
    return None


async def _extract_guest_opinion_metrics(page: Page, config: SiteConfig) -> dict[str, str]:
    """Extract likes and dislikes from Analytics -> Guest opinion."""
    try:
        await _open_guest_opinion(page, config)
        await _prepare_guest_opinion_table(page, config)
        tables = await _extract_tables_all_columns(page, config.data_selectors.get("tables", "table"))
        row = _find_row_by_text(tables, config.data_selectors.get("analytics_search_text", "химки"))
        if not row:
            print("Analytics: row with Himki was not found. Saving debug artifacts...")
            await _save_debug_artifacts(page, "guest_opinion_not_found")
            return {}
        print(f"Analytics: row found: {row}")
        return row
    except Exception:
        await _save_debug_artifacts(page, "guest_opinion")
        return {}


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


async def _save_debug_artifacts(page: Page, label: str = "monthly_statistics") -> None:
    debug_dir = Path(__file__).resolve().parent / "debug_output"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    await page.screenshot(path=debug_dir / f"{label}_{timestamp}.png", full_page=True)
    html = await page.content()
    (debug_dir / f"{label}_{timestamp}.html").write_text(html, encoding="utf-8")


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
            await _goto(page, config.url, config)
            await _try_login(page, config)
            await _open_operational_days_tab(page, config)

            table_selector = config.data_selectors.get("tables", "table")
            card_selector = config.data_selectors.get("cards", "[data-testid], .card, .tile, .widget")

            try:
                await page.wait_for_selector(f"{table_selector}, {card_selector}", timeout=config.timeout_ms)
            except PlaywrightTimeoutError:
                # The report will still include a diagnostic sheet instead of failing silently.
                pass

            tables = await _extract_tables_all_columns(page, table_selector)
            cards = await _extract_cards(page, card_selector)
            last_day = _find_last_day_row(tables)
            if not tables and not cards:
                await _save_debug_artifacts(page)

            analytics = await _extract_guest_opinion_metrics(page, config)

            await context.storage_state(path=config.storage_state_path)

            return ParsedReportData(
                source_url=config.url,
                collected_at=datetime.now(),
                tables=tables,
                cards=cards,
                last_day=last_day,
                analytics=analytics,
            )
        finally:
            await browser.close()
