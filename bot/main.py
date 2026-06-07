import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from config import load_config
from parser import get_monthly_statistics
from report import create_excel_report


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
    await message.answer("Бот готов. Используйте /report, чтобы собрать Excel-отчёт.")


@dp.message(Command("report"))
async def report_command(message: Message) -> None:
    """Run parser, build Excel, and send it back to Telegram."""
    if not _is_allowed(message):
        await message.answer("У вас нет доступа к этому боту.")
        return

    status_message = await message.answer("Собираю данные с сайта и формирую Excel-отчёт...")

    try:
        parsed_data = await get_monthly_statistics(config.site)
        report_path = create_excel_report(parsed_data, config.report)
        await message.answer_document(
            FSInputFile(report_path),
            caption="Готово. В Excel есть лист Last day с последним днём месяца.",
        )
        await status_message.delete()
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
