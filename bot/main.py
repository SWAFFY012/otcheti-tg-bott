import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import Message

from config import load_config
from parser import get_monthly_statistics
from report import build_text_report


logging.basicConfig(level=logging.INFO)
config = load_config()

if not config.telegram.token:
    raise SystemExit("Set BOT_TOKEN or TOKEN before starting the bot.")

dp = Dispatcher()


def _is_allowed(message: Message) -> bool:
    allowed_ids = config.telegram.allowed_user_ids
    return not allowed_ids or (message.from_user and message.from_user.id in allowed_ids)


@dp.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer("Бот готов. Используйте /report, чтобы получить отчёт.")


@dp.message(Command("report"))
async def report_command(message: Message) -> None:
    """Run parser, build a short text report, and send it to Telegram."""
    if not _is_allowed(message):
        await message.answer("У вас нет доступа к этому боту.")
        return

    status_message = await message.answer("Собираю данные с сайта...")

    try:
        parsed_data = await get_monthly_statistics(config.site)
        report_text = build_text_report(parsed_data)
        await status_message.edit_text(report_text)
    except Exception as exc:
        logging.exception("Report generation failed")
        await status_message.edit_text(f"Не удалось сформировать отчёт: {exc}")


@dp.message(F.text)
async def unknown_text(message: Message) -> None:
    await message.answer("Я понимаю команду /report.")


async def _run_with_retries(action, description: str, attempts: int = 5):
    """Retry Telegram startup calls because local network timeouts are common on Windows."""
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except TelegramNetworkError as exc:
            last_error = exc
            wait_seconds = min(attempt * 5, 20)
            logging.warning(
                "%s failed (%s/%s): %s. Retrying in %s seconds...",
                description,
                attempt,
                attempts,
                exc,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    raise RuntimeError(
        "Не могу подключиться к Telegram api.telegram.org:443. "
        "Проверьте интернет, VPN/прокси, антивирус/фаервол и попробуйте снова."
    ) from last_error


async def main() -> None:
    bot = Bot(token=config.telegram.token)

    try:
        # Polling cannot work while Telegram sends updates to an old webhook URL.
        await _run_with_retries(lambda: bot.delete_webhook(drop_pending_updates=True), "delete_webhook")
        me = await _run_with_retries(bot.get_me, "get_me")
        print(f"Бот запущен: @{me.username}. Оставьте это окно открытым.")
        await dp.start_polling(bot)
    except RuntimeError as exc:
        print(exc)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
