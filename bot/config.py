import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    allowed_user_ids: list[int]


@dataclass(frozen=True)
class SiteConfig:
    url: str
    login: str
    password: str
    headless: bool
    timeout_ms: int
    login_selectors: dict[str, str]
    data_selectors: dict[str, str]


@dataclass(frozen=True)
class ReportConfig:
    output_dir: Path
    file_prefix: str


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    site: SiteConfig
    report: ReportConfig


def _read_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config() -> AppConfig:
    """Load config.json and let environment variables override secrets."""
    raw = _read_config()
    telegram = raw["telegram"]
    site = raw["site"]
    report = raw["report"]

    token = os.environ.get("BOT_TOKEN") or os.environ.get("TOKEN") or telegram.get("token", "")
    login = os.environ.get("SITE_LOGIN") or site.get("login", "")
    password = os.environ.get("SITE_PASSWORD") or site.get("password", "")

    output_dir = Path(report.get("output_dir", "reports"))
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    return AppConfig(
        telegram=TelegramConfig(
            token=token,
            allowed_user_ids=[int(user_id) for user_id in telegram.get("allowed_user_ids", [])],
        ),
        site=SiteConfig(
            url=site["url"],
            login=login,
            password=password,
            headless=bool(site.get("headless", True)),
            timeout_ms=int(site.get("timeout_ms", 60000)),
            login_selectors=site.get("login_selectors", {}),
            data_selectors=site.get("data_selectors", {}),
        ),
        report=ReportConfig(
            output_dir=output_dir,
            file_prefix=report.get("file_prefix", "report"),
        ),
    )
