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
python main.py
```

Перед запуском создайте файл `bot/.env` по примеру `bot/.env.example`:

```text
BOT_TOKEN=telegram_bot_token
SITE_LOGIN=office_manager_login
SITE_PASSWORD=office_manager_password
```

Этот файл не загружается в GitHub, поэтому токен и пароль останутся на сервере.

Если сайт поменяет вёрстку, поправьте CSS-селекторы в `bot/config.json`.

## Деплой на Render

Для `/report`-бота нужен Render Background Worker, а не Web Service. В репозитории есть
`render.yaml` и `Dockerfile`, поэтому Render может собрать проект автоматически.

1. Откройте Render Dashboard.
2. Выберите `New` -> `Blueprint`.
3. Выберите репозиторий `SWAFFY012/otcheti-tg-bott`.
4. Render найдёт `render.yaml` и создаст worker `otcheti-tg-bott`.
5. В Environment Variables введите:
   - `BOT_TOKEN` - токен Telegram-бота
   - `SITE_LOGIN` - логин OfficeManager
   - `SITE_PASSWORD` - пароль OfficeManager
6. Запустите Deploy.

Если создаёте вручную через `New` -> `Background Worker`, используйте Docker runtime.

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
