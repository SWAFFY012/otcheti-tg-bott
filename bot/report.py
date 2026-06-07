from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import ReportConfig
from parser import ParsedReportData


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
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

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
                            "Данные не найдены. Проверьте авторизацию и CSS-селекторы "
                            "в bot/config.json."
                        )
                    }
                ]
            ).to_excel(writer, sheet_name="No data", index=False)

    return report_path
