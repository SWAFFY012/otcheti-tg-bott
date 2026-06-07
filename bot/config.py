import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"


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
    storage_state_path: Path
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


def _load_env_file() -> None:
    """Load simple KEY=VALUE lines from bot/.env without requiring extra packages."""
    if not ENV_PATH.exists():
        return

    with ENV_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def load_config() -> AppConfig:
    """Load config.json and let environment variables override secrets."""
    _load_env_file()
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

    storage_state_path = Path(site.get("storage_state_path", "auth_state.json"))
    if not storage_state_path.is_absolute():
        storage_state_path = BASE_DIR / storage_state_path

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
            storage_state_path=storage_state_path,
            login_selectors=site.get("login_selectors", {}),
            data_selectors=site.get("data_selectors", {}),
        ),
        report=ReportConfig(
            output_dir=output_dir,
            file_prefix=report.get("file_prefix", "report"),
        ),
    )
