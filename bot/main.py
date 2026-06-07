import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from config import load_config
from parser import get_monthly_statistics
from report import build_text_report


logging.basicConfig(level=logging.INFO)
config = load_config()

if not config.telegram.token:
    raise SystemExit("Set BOT_TOKEN or TOKEN before starting the bot.")

bot = Bot(token=config.telegram.token)
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


async def main() -> None:
    # Polling cannot work while Telegram sends updates to an old webhook URL.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
