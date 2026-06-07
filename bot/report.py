from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import ReportConfig
from parser import ParsedReportData


def _normalize_key(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _get_value(row: dict[str, str], candidates: list[str], default: str = "0") -> str:
    normalized_row = {_normalize_key(key): value for key, value in row.items()}

    for candidate in candidates:
        value = normalized_row.get(_normalize_key(candidate))
        if value not in (None, ""):
            return value.strip()

    return default


def _clean_number(value: str) -> str:
    cleaned = value.replace("\xa0", " ").strip()
    if cleaned.endswith(",00"):
        cleaned = cleaned[:-3]
    return cleaned.replace(" ", "")


def _clean_percent(value: str) -> str:
    cleaned = value.replace("\xa0", " ").replace(" ", "").strip()
    return cleaned or "0%"


def build_text_report(data: ParsedReportData) -> str:
    """Build the short Telegram report from the last operational day row."""
    if not data.last_day:
        raise RuntimeError("Не нашёл строку последнего дня месяца в таблице.")

    row = data.last_day
    analytics = data.analytics or {}
    day = _get_value(row, ["Дата", "column_1"], "")
    date_str = data.collected_at.strftime("%d.%m.%Y")
    if day.isdigit():
        try:
            date_str = data.collected_at.replace(day=int(day)).strftime("%d.%m.%Y")
        except ValueError:
            date_str = f"{int(day):02d}.{data.collected_at.strftime('%m.%Y')}"

    revenue = _clean_number(_get_value(row, ["Выручка, руб.", "Выручка"], "0"))
    revenue_growth = _clean_percent(_get_value(row, ["Прирост выручки, %", "Прирост выручки"], "0%"))
    orders = _clean_number(_get_value(row, ["Заказы, шт.", "Заказы"], "0"))
    average_check = _clean_number(_get_value(row, ["Средний чек, руб.", "Средний чек"], "0"))
    average_speed = _get_value(row, ["Скорость кухни", "Средняя скорость", "Среднее время приготовления"], "0")
    long_orders = _clean_number(_get_value(row, ["Долгие заказы", "Долгих", "Долгие", "Долгих заказов"], "0"))
    likes = _clean_number(_get_value(analytics, ["Лайки, #", "Лайки"], "0"))
    dislikes = _clean_number(_get_value(analytics, ["Дизлайки, #", "Дизлайки"], "0"))
    new_guests = _clean_number(_get_value(row, ["Новых клиентов", "Новых гостей", "Новые гости"], "0"))
    old_guests = _clean_number(_get_value(row, ["Старых клиентов", "Старых гостей", "Старые гости"], "0"))

    return "\n".join(
        [
            f"Отчёт Мега Химки {date_str}:",
            f"Выручка - {revenue} ({revenue_growth})",
            f"Заказы - {orders}",
            f"Средний чек - {average_check}",
            f"Средняя скорость - {average_speed}",
            f"Долгих - {long_orders}",
            f"Лайки - {likes}",
            f"Дизлайки - {dislikes}",
            f"Новых гостей - {new_guests}",
            f"Старых гостей - {old_guests}",
        ]
    )


def _safe_sheet_name(name: str) -> str:
    invalid_chars = set('[]:*?/\\')
    safe = "".join(char if char not in invalid_chars else "_" for char in name)
    return safe[:31] or "sheet"


def create_excel_report(data: ParsedReportData, config: ReportConfig) -> Path:
    """Create an Excel report from parsed OfficeManager data."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = data.collected_at.strftime("%Y%m%d_%H%M%S")
    report_path = config.output_dir / f"{config.file_prefix}_{timestamp}.xlsx"

    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        summary = pd.DataFrame(
            [
                {"Параметр": "Источник", "Значение": data.source_url},
                {"Параметр": "Дата сбора", "Значение": data.collected_at.strftime("%d.%m.%Y %H:%M:%S")},
                {"Параметр": "Таблиц найдено", "Значение": len(data.tables)},
                {"Параметр": "Карточек найдено", "Значение": len(data.cards)},
                {"Параметр": "Последний день найден", "Значение": "да" if data.last_day else "нет"},
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        if data.last_day:
            pd.DataFrame([data.last_day]).to_excel(writer, sheet_name="Last day", index=False)

        if data.cards:
            pd.DataFrame(data.cards).to_excel(writer, sheet_name="Cards", index=False)

        for index, table in enumerate(data.tables, start=1):
            rows = table.get("rows", [])
            if not rows:
                continue
            sheet_name = _safe_sheet_name(table.get("name") or f"Table {index}")
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)

        if not data.tables and not data.cards:
            pd.DataFrame(
                [
                    {
                        "Сообщение": (
                            "Данные не найдены. Проверьте авторизацию, сохранённую сессию "
                            "и CSS-селекторы в bot/config.json."
                        )
                    }
                ]
            ).to_excel(writer, sheet_name="No data", index=False)

    return report_path
