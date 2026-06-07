# Отчёт Мега Химки Telegram Bot

Бот для создания короткого отчёта Мега Химки.

## Автоматический Excel-отчёт с сайта

Новый модуль `bot/` запускает Telegram-бота на `aiogram 3`.
Команда `/report` открывает сайт OfficeManager через Playwright, при необходимости авторизуется,
собирает видимые таблицы и карточки со страницы, создаёт Excel-файл через `pandas` и `openpyxl`,
а затем отправляет отчёт пользователю в Telegram.

Структура:

```text
bot/
├── main.py
├── parser.py
├── report.py
├── config.py
├── config.json
├── reports/
└── requirements.txt
```

Запуск на сервере с Python 3.12:

```bash
cd bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
set BOT_TOKEN=telegram_bot_token
set SITE_LOGIN=office_manager_login
set SITE_PASSWORD=office_manager_password
python main.py
```

На Linux-сервере переменные задаются так:

```bash
export BOT_TOKEN="telegram_bot_token"
export SITE_LOGIN="office_manager_login"
export SITE_PASSWORD="office_manager_password"
python main.py
```

Если сайт поменяет вёрстку, поправьте CSS-селекторы в `bot/config.json`.

## Поля отчёта

Бот спрашивает:

1. Выручка
2. Заказы
3. Средний чек
4. Средняя скорость в формате `мм:сс`
5. Долгих
6. Лайки
7. Дизлайки
8. Новых гостей
9. Старых гостей

В конце бот отправляет отчёт:

```text
Отчёт Мега Химки 31.05.2026:
Выручка - 23
Заказы - 23
Средний чек - 0
Средняя скорость - 23:34
Долгих - 4
Лайки - 1
Дизлайки - 4
Новых гостей - 7
Старых гостей - 77
```

## Настройка

### Запуск без домена

Для запуска на компьютере нужен Python. Откройте терминал в папке проекта и выполните:

```powershell
$env:TOKEN="telegram_bot_token"
python polling_bot.py
```

Пока окно терминала открыто, бот работает. Если закрыть терминал или выключить компьютер, бот остановится.

`polling_bot.py` сам отключает webhook через `deleteWebhook`, чтобы Telegram начал отдавать сообщения через polling.

### Запуск через Vercel webhook

В Vercel нужно добавить переменную окружения:

```text
TOKEN=telegram_bot_token
```

После деплоя подключить webhook:

```text
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-domain>/api/webhook
```
