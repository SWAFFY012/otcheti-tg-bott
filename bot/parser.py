from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

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
        for index in range(await locator.count()):
            item = locator.nth(index)
            if not await item.is_visible():
                continue
            await item.click()
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


async def _scroll_vertical_areas(page: Page, delta: int) -> None:
    """Scroll the page and dashboard containers; Superset often keeps data inside nested panes."""
    await page.evaluate(
        """delta => {
            window.scrollBy(0, delta);
            for (const element of document.querySelectorAll('*')) {
                if (element.scrollHeight > element.clientHeight + 40) {
                    element.scrollTop = Math.min(element.scrollTop + delta, element.scrollHeight);
                }
            }
        }""",
        delta,
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


def _first_number(text: str) -> str:
    match = re.search(r"-?\d+(?:[\s\xa0]\d{3})*(?:[,.]\d+)?", text)
    return match.group(0).replace("\xa0", " ").strip() if match else ""


def _first_time(text: str) -> str:
    match = re.search(r"\b\d{1,2}:\d{2}\b", text)
    return match.group(0) if match else ""


def _find_metric_near_keywords(lines: list[str], keywords: list[str], *, time_value: bool = False) -> str:
    """Find a number/time on the same line or the next few lines after a metric label."""
    extractor = _first_time if time_value else _first_number

    for index, line in enumerate(lines):
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue

        for candidate in [line, *lines[index + 1 : index + 4]]:
            value = extractor(candidate)
            if value:
                return value

    return ""


def _find_time_before_label(lines: list[str], label: str) -> str:
    """Find a time value immediately before a label such as 'среднее за день'."""
    label = label.lower()
    for index, line in enumerate(lines):
        if label not in line.lower():
            continue

        for candidate in reversed(lines[max(0, index - 3) : index + 1]):
            value = _first_time(candidate)
            if value:
                return value

    return ""


def _is_green_rgb(value: str) -> bool:
    numbers = [int(number) for number in re.findall(r"\d+", value)[:3]]
    return len(numbers) == 3 and numbers[1] > numbers[0] + 25 and numbers[1] > numbers[2] + 10


def _is_red_rgb(value: str) -> bool:
    numbers = [int(number) for number in re.findall(r"\d+", value)[:3]]
    return len(numbers) == 3 and numbers[0] > numbers[1] + 25 and numbers[0] > numbers[2] + 10


async def _extract_colored_motivation_numbers(page: Page) -> dict[str, str]:
    """Fallback for motivation board cards where likes/dislikes are shown only by color."""
    elements = await page.evaluate(
        """() => [...document.querySelectorAll('body *')].map((element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const text = (element.innerText || '').trim();
            return {
                text,
                color: style.color,
                background: style.backgroundColor,
                visible: rect.width > 0 && rect.height > 0,
            };
        }).filter((item) => item.visible && item.text && item.text.length <= 40)"""
    )

    result: dict[str, str] = {}
    for item in elements:
        value = _first_number(str(item.get("text", "")))
        if not value:
            continue

        color = f"{item.get('color', '')} {item.get('background', '')}"
        if "Лайки, #" not in result and _is_green_rgb(color):
            result["Лайки, #"] = value
        if "Дизлайки, #" not in result and _is_red_rgb(color):
            result["Дизлайки, #"] = value
        if "Лайки, #" in result and "Дизлайки, #" in result:
            break

    return result


async def _extract_motivationboard_exact_values(page: Page) -> dict[str, str]:
    """Read known motivation board widgets by their rendered attributes and labels."""
    return await page.evaluate(
        """() => {
            const result = {};
            const readThumb = (color) => {
                const cards = [...document.querySelectorAll(`div[backgroundcolor="#ffffff"][color="${color}"]`)];
                for (const card of cards) {
                    const text = (card.innerText || '').trim();
                    const match = text.match(/\\d+/);
                    if (match) return match[0];
                }
                return '';
            };

            const red = readThumb('#FF5050');
            const green = readThumb('#2FCF07');
            if (red) result['Дизлайки, #'] = red;
            if (green) result['Лайки, #'] = green;

            const labels = [...document.querySelectorAll('span')];
            const dayLabel = labels.find((span) => (span.innerText || '').trim().toLowerCase() === 'среднее за день');
            if (dayLabel && dayLabel.parentElement) {
                const time = [...dayLabel.parentElement.querySelectorAll('span')]
                    .map((span) => (span.innerText || '').trim())
                    .find((text) => /^\\d{1,2}:\\d{2}$/.test(text));
                if (time) result['Среднее время приготовления за день'] = time;
            }

            return result;
        }"""
    )


async def _extract_motivationboard_metrics(context: BrowserContext, config: SiteConfig) -> dict[str, str]:
    """Open the motivation board and parse likes, dislikes, and daily average cooking time."""
    url = config.data_selectors.get("motivationboard_url", "")
    if not url:
        return {}

    page = await context.new_page()
    page.set_default_timeout(config.timeout_ms)

    try:
        print("Motivationboard: opening board...")
        await _goto(page, url, config)
        await _try_login(page, config)
        await page.wait_for_timeout(10000)
        await _save_debug_artifacts(page, "motivationboard")

        result = await _extract_motivationboard_exact_values(page)
        text = await page.locator("body").inner_text()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        fallback = {
            "Лайки, #": _find_metric_near_keywords(lines, ["лайк", "позитив"]),
            "Дизлайки, #": _find_metric_near_keywords(lines, ["дизлайк", "негатив"]),
            "Среднее время приготовления за день": _find_time_before_label(lines, "среднее за день")
            or _find_metric_near_keywords(
                lines,
                ["среднее время приготовления", "время приготовления", "среднее время", "готов"],
                time_value=True,
            ),
        }

        colored = await _extract_colored_motivation_numbers(page)
        for source in (fallback, colored):
            for key, value in source.items():
                if value and not result.get(key):
                    result[key] = value

        return {key: value for key, value in result.items() if value}
    except Exception:
        await _save_debug_artifacts(page, "motivationboard_error")
        return {}
    finally:
        await page.close()


async def _open_guest_opinion(page: Page, config: SiteConfig) -> None:
    """Open the exact Analytics -> Guest opinion page and switch to operational metrics."""
    analytics_url = config.data_selectors.get(
        "analytics_url",
        "https://officemanager.dodois.io/OfficeManager/Analytics/customer_opinion",
    )
    guest_opinion_text = config.data_selectors.get("guest_opinion_text", "Гостевое мнение")

    await _goto(page, analytics_url, config)
    await _wait_for_analytics_content(page, config)

    if await page.get_by_text(guest_opinion_text, exact=True).count() == 0:
        print("Analytics: opening guest opinion...")
        await _click_text(page, guest_opinion_text, config)
        await _wait_for_analytics_content(page, config)

    metrics_tab_text = config.data_selectors.get(
        "guest_metrics_tab_text",
        "Дизлайки и операционные метрики",
    )
    print("Analytics: opening dislikes and operational metrics...")
    if not await _click_text(page, metrics_tab_text, config):
        await page.locator("[role='tab']").filter(has_text=metrics_tab_text).first.click()
        await _settle_after_click(page, config)
    await _wait_for_analytics_content(page, config)


async def _wait_for_analytics_content(page: Page, config: SiteConfig) -> None:
    """Wait until Superset renders at least one chart/table instead of an empty canvas."""
    for _ in range(24):
        content_count = await page.locator("[data-test-chart-id], table, canvas").count()
        has_loaded_text = await page.get_by_text("Период доступных данных", exact=False).count() > 0
        if content_count > 0 or has_loaded_text:
            await page.wait_for_timeout(2500)
            return
        await page.wait_for_timeout(1000)


async def _select_analytics_period(page: Page, period_text: str, config: SiteConfig) -> None:
    """Choose the period in the analytics filter panel when it is not already selected."""
    if "native_filters_key=" in page.url:
        return

    if await page.get_by_text(period_text, exact=True).count() > 0:
        return

    period_filter = page.locator("xpath=//*[normalize-space()='Период*']/following::input[1]").first
    if await period_filter.count() == 0:
        period_filter = page.locator("xpath=//*[normalize-space()='Период']/following::input[1]").first
    if await period_filter.count() == 0:
        return

    await period_filter.click()
    await _settle_after_click(page, config)
    if await _click_text(page, period_text, config):
        await _click_text(page, "Применить", config)
        await page.wait_for_timeout(8000)


async def _scroll_to_text(page: Page, text: str) -> bool:
    """Scroll until the target section becomes visible."""
    section = page.get_by_text(text, exact=True)
    for _ in range(18):
        if await section.count() > 0 and await section.first.is_visible():
            await section.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(700)
            return True
        await _scroll_vertical_areas(page, 900)
    return False


async def _fill_scores_search(page: Page, section_text: str, search_text: str) -> bool:
    """Fill only the search input under the coffee-shop scores section, not the left menu search."""
    filled = await page.evaluate(
        """({ sectionText, searchText }) => {
            const elements = [...document.querySelectorAll('body *')];
            const section = elements.find((element) => {
                const text = (element.innerText || '').trim();
                return text === sectionText;
            });

            if (!section) {
                return false;
            }

            const sectionRect = section.getBoundingClientRect();
            const inputs = [...document.querySelectorAll('input')].filter((input) => {
                const rect = input.getBoundingClientRect();
                const placeholder = (input.getAttribute('placeholder') || '').toLowerCase();
                const isVisible = rect.width > 20 && rect.height > 10;
                const isBelowSection = rect.top > sectionRect.bottom && rect.top < sectionRect.bottom + 260;
                const isNearSection = rect.left >= sectionRect.left - 40;
                return isVisible && isBelowSection && isNearSection && placeholder.includes('поиск');
            });

            const input = inputs[0];
            if (!input) {
                return false;
            }

            input.scrollIntoView({ block: 'center', inline: 'nearest' });
            input.focus();
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, searchText);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
            return true;
        }""",
        {"sectionText": section_text, "searchText": search_text},
    )
    if filled:
        await page.wait_for_timeout(3500)
    return bool(filled)


async def _prepare_guest_opinion_table(page: Page, config: SiteConfig) -> None:
    """Set the analytics filters as closely as possible to the screen flow."""
    period_text = config.data_selectors.get("analytics_period_text", "Последние сутки")
    search_text = config.data_selectors.get("analytics_search_text", "химки")
    section_text = config.data_selectors.get("analytics_scores_section_text", "Оценки за весь период по кофейням")

    await _select_analytics_period(page, period_text, config)
    await page.keyboard.press("Escape")

    await _scroll_to_text(page, section_text)

    print(f"Analytics: typing search '{search_text}' in scores section...")
    if not await _fill_scores_search(page, section_text, search_text):
        print("Analytics: scores search input was not found.")
        await _save_debug_artifacts(page, "scores_search_not_found")


def _find_row_by_text(tables: list[dict], needle: str) -> dict[str, str] | None:
    needle = needle.lower()
    for table in tables:
        for row in table.get("rows", []):
            if needle in " ".join(row.values()).lower():
                return _merge_related_rows(tables, row)
    return None


def _is_plain_number(value: str) -> bool:
    value = value.replace("\xa0", " ").replace(" ", "").strip()
    return bool(re.fullmatch(r"\d+(?:[,.]\d+)?", value))


def _is_percent(value: str) -> bool:
    value = value.replace("\xa0", " ").replace(" ", "").strip()
    return bool(re.fullmatch(r"\d+(?:[,.]\d+)?%", value))


def _find_guest_scores_row(tables: list[dict], needle: str) -> dict[str, str] | None:
    """Find the coffee-shop scores table row by its value pattern after the shop name."""
    needle = needle.lower()

    for table in tables:
        for raw_row in table.get("rows", []):
            row = _merge_related_rows(tables, raw_row)
            cells = [
                str(value).strip()
                for key, value in row.items()
                if not key.startswith("__") and str(value).strip()
            ]

            for index, value in enumerate(cells):
                if needle not in value.lower():
                    continue

                tail = cells[index + 1 :]
                if (
                    len(tail) >= 5
                    and _is_plain_number(tail[0])
                    and _is_plain_number(tail[1])
                    and _is_percent(tail[2])
                    and _is_plain_number(tail[3])
                    and _is_plain_number(tail[4])
                ):
                    return {**row, "Лайки, #": tail[3], "Дизлайки, #": tail[4]}

    return {}


async def _extract_guest_opinion_metrics_from_text(page: Page, needle: str) -> dict[str, str]:
    """Fallback for virtualized grids that expose cells as text instead of normal table markup."""
    lines = [line.strip() for line in (await page.locator("body").inner_text()).splitlines() if line.strip()]
    needle = needle.lower()

    for index, line in enumerate(lines):
        if needle not in line.lower():
            continue

        values: list[str] = []
        for value_line in lines[index + 1 : index + 30]:
            if "итого" in value_line.lower():
                break
            values.extend(re.findall(r"[+-]?\d+(?:[\s\u00a0]\d{3})*(?:[,.]\d+)?%?", value_line))
            non_percent_values = [value for value in values if not value.endswith("%")]
            if len(non_percent_values) >= 4:
                return {"Лайки, #": non_percent_values[2], "Дизлайки, #": non_percent_values[3]}

    return {}


async def _scroll_guest_row_into_view(page: Page, needle: str) -> None:
    """Move the matched coffee-shop row into the screenshot viewport for visual checks."""
    await page.evaluate(
        """needle => {
            const lowerNeedle = needle.toLowerCase();
            const elements = [...document.querySelectorAll('body *')];
            const row = elements.find((element) => {
                const text = (element.innerText || '').toLowerCase();
                const rect = element.getBoundingClientRect();
                return text.includes(lowerNeedle) && rect.width > 0 && rect.height > 0;
            });

            if (row) {
                row.scrollIntoView({ block: 'center', inline: 'center' });
            }
        }""",
        needle,
    )
    await page.wait_for_timeout(1000)


async def _extract_guest_opinion_metrics(page: Page, config: SiteConfig) -> dict[str, str]:
    """Extract likes and dislikes from Analytics -> Guest opinion."""
    try:
        await _open_guest_opinion(page, config)
        await _prepare_guest_opinion_table(page, config)
        tables = await _extract_tables_all_columns(page, config.data_selectors.get("tables", "table"))
        search_text = config.data_selectors.get("analytics_search_text", "химки")
        row = _find_guest_scores_row(tables, search_text)
        if not row:
            row = _find_row_by_text(tables, search_text)
        if not row:
            row = await _extract_guest_opinion_metrics_from_text(page, search_text)
        if not row:
            print("Analytics: row with Himki was not found. Saving debug artifacts...")
            await _save_debug_artifacts(page, "guest_opinion_not_found")
            return {}
        await _scroll_guest_row_into_view(page, search_text)
        await _save_debug_artifacts(page, "guest_opinion_row_found")
        await _save_guest_row_values_screenshot(page, row)
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


async def _save_guest_row_values_screenshot(page: Page, row: dict[str, str]) -> None:
    """Save a readable screenshot of the exact analytics row values used by the bot."""
    debug_dir = Path(__file__).resolve().parent / "debug_output"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    shop = next((value for value in row.values() if "Химки" in str(value)), "Химки")
    orders = next((value for key, value in row.items() if key == "966"), "")
    rated_orders = next((value for key, value in row.items() if key == "64"), "")
    rated_share = next((value for key, value in row.items() if key == "6.63%"), "")
    likes = row.get("Лайки, #", "")
    dislikes = row.get("Дизлайки, #", "")

    content = f"""
    <!doctype html>
    <html lang="ru">
      <head>
        <meta charset="utf-8">
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; color: #111; }}
          h1 {{ font-size: 22px; margin: 0 0 18px; }}
          table {{ border-collapse: collapse; font-size: 18px; }}
          th, td {{ border: 1px solid #bbb; padding: 12px 16px; text-align: left; }}
          th {{ background: #f3f3f3; }}
        </style>
      </head>
      <body>
        <h1>Проверка строки таблицы: Оценки за весь период по кофейням</h1>
        <table>
          <tr>
            <th>Кофейня</th>
            <th>Кол-во заказов</th>
            <th>Оцененных заказов</th>
            <th>Доля оцененных</th>
            <th>Лайки</th>
            <th>Дизлайки</th>
          </tr>
          <tr>
            <td>{html.escape(str(shop))}</td>
            <td>{html.escape(str(orders))}</td>
            <td>{html.escape(str(rated_orders))}</td>
            <td>{html.escape(str(rated_share))}</td>
            <td>{html.escape(str(likes))}</td>
            <td>{html.escape(str(dislikes))}</td>
          </tr>
        </table>
      </body>
    </html>
    """

    summary_page = await page.context.new_page()
    try:
        await summary_page.set_content(content)
        await summary_page.screenshot(path=debug_dir / f"guest_opinion_row_values_{timestamp}.png", full_page=True)
    finally:
        await summary_page.close()


async def get_monthly_statistics(config: SiteConfig) -> ParsedReportData:
    """Open OfficeManager, authorize if needed, wait for JavaScript data, and parse visible data."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.headless)
        context_options = {}
        if config.storage_state_path.exists():
            context_options["storage_state"] = str(config.storage_state_path)

        context = await browser.new_context(viewport={"width": 1920, "height": 1080}, **context_options)
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

            analytics = await _extract_motivationboard_metrics(context, config)

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
