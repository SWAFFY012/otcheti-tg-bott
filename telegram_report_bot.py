import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from datetime import datetime

TOKEN = '8929830688:AAFoQMeM0ZourQuWkOZCIjBpInB8QpkCWSM'

VYRUCHKA, ZAKAZY, SREDNIY_CHEK, SREDNYAYA_SKOROST, DOLGIH, LAYKI, DIZLAYKI, NOVYH_GOSTEY, STARYH_GOSTEY = range(9)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Привет! Я помогу создать отчет для Мега Химки.\n'
        'Введите выручку:'
    )
    return VYRUCHKA

async def vyruchka(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vyruchka'] = update.message.text
    await update.message.reply_text('Введите количество заказов:')
    return ZAKAZY

async def zakazy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['zakazy'] = update.message.text

    try:
        vyruchka = float(context.user_data['vyruchka'])
        zakazy_count = int(update.message.text)
        sredniy_chek = vyruchka / zakazy_count if zakazy_count > 0 else 0
        context.user_data['sredniy_chek'] = f"{sredniy_chek:.2f}"
    except:
        context.user_data['sredniy_chek'] = "0"

    await update.message.reply_text('Введите среднюю скорость (формат: 03:16):')
    return SREDNYAYA_SKOROST

async def srednyaya_skorost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srednyaya_skorost'] = update.message.text
    await update.message.reply_text('Введите количество долгих заказов:')
    return DOLGIH

async def dolgih(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dolgih'] = update.message.text
    await update.message.reply_text('Введите количество лайков:')
    return LAYKI

async def layki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['layki'] = update.message.text
    await update.message.reply_text('Введите количество дизлайков:')
    return DIZLAYKI

async def dizlayki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dizlayki'] = update.message.text
    await update.message.reply_text('Введите количество новых гостей:')
    return NOVYH_GOSTEY

async def novyh_gostey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['novyh_gostey'] = update.message.text
    await update.message.reply_text('Введите количество старых гостей:')
    return STARYH_GOSTEY

async def staryh_gostey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['staryh_gostey'] = update.message.text

    date_str = datetime.now().strftime('%d.%m.%Y')

    report = f"""Отчёт Мега Химки {date_str}:
Выручка - {context.user_data['vyruchka']}
Заказы - {context.user_data['zakazy']}
Средний чек - {context.user_data['sredniy_chek']}
Средняя скорость - {context.user_data['srednyaya_skorost']}
Долгих - {context.user_data['dolgih']}
Лайки - {context.user_data['layki']}
Дизлайки - {context.user_data['dizlayki']}
Новых гостей - {context.user_data['novyh_gostey']}
Старых гостей - {context.user_data['staryh_gostey']}"""

    await update.message.reply_text(report)
    await update.message.reply_text('\nОтчет готов! Чтобы создать новый отчет, используйте /start')

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Отчет отменен. Используйте /start для создания нового отчета.')
    return ConversationHandler.END

def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            VYRUCHKA: [MessageHandler(filters.TEXT & ~filters.COMMAND, vyruchka)],
            ZAKAZY: [MessageHandler(filters.TEXT & ~filters.COMMAND, zakazy)],
            SREDNYAYA_SKOROST: [MessageHandler(filters.TEXT & ~filters.COMMAND, srednyaya_skorost)],
            DOLGIH: [MessageHandler(filters.TEXT & ~filters.COMMAND, dolgih)],
            LAYKI: [MessageHandler(filters.TEXT & ~filters.COMMAND, layki)],
            DIZLAYKI: [MessageHandler(filters.TEXT & ~filters.COMMAND, dizlayki)],
            NOVYH_GOSTEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, novyh_gostey)],
            STARYH_GOSTEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, staryh_gostey)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)

    print('Бот запущен...')
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
