import json
import os
import re
import time
from datetime import datetime
from urllib import parse, request


TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise SystemExit("Set TOKEN environment variable before starting the bot.")

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

FIELDS = [
    ("revenue", "Выручка", "Введите выручку:"),
    ("orders", "Заказы", "Введите количество заказов:"),
    ("average_check", "Средний чек", "Введите средний чек:"),
    ("average_speed", "Средняя скорость", "Введите среднюю скорость в формате мм:сс:"),
    ("long_orders", "Долгих", "Введите количество долгих заказов:"),
    ("likes", "Лайки", "Введите количество лайков:"),
    ("dislikes", "Дизлайки", "Введите количество дизлайков:"),
    ("new_guests", "Новых гостей", "Введите количество новых гостей:"),
    ("old_guests", "Старых гостей", "Введите количество старых гостей:"),
]

SPEED_RE = re.compile(r"^\d{1,3}:[0-5]\d$")
sessions = {}


def telegram(method, payload=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(f"{TELEGRAM_API}/{method}", data=data, headers=headers)
    with request.urlopen(req, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def send_message(chat_id, text):
    telegram("sendMessage", {"chat_id": chat_id, "text": text})


def start_report(chat_id):
    sessions[chat_id] = {"step": 0, "answers": {}}
    send_message(chat_id, "Привет! Я помогу создать отчёт Мега Химки.\n" + FIELDS[0][2])


def build_report(answers):
    lines = [f"Отчёт Мега Химки {datetime.now().strftime('%d.%m.%Y')}:"]
    for key, label, _prompt in FIELDS:
        lines.append(f"{label} - {answers[key]}")
    return "\n".join(lines)


def handle_answer(chat_id, text):
    session = sessions.get(chat_id)
    if session is None:
        start_report(chat_id)
        return

    step = session["step"]
    key, _label, _prompt = FIELDS[step]
    value = text.strip()

    if key == "average_speed" and not SPEED_RE.fullmatch(value):
        send_message(chat_id, "Средняя скорость должна быть в формате мм:сс, например 03:16.")
        return

    session["answers"][key] = value
    step += 1

    if step >= len(FIELDS):
        report = build_report(session["answers"])
        sessions.pop(chat_id, None)
        send_message(chat_id, report)
        return

    session["step"] = step
    send_message(chat_id, FIELDS[step][2])


def handle_update(update):
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    if text.startswith("/start"):
        start_report(chat_id)
        return

    if text.startswith("/cancel"):
        sessions.pop(chat_id, None)
        send_message(chat_id, "Отчёт отменён. Чтобы создать новый отчёт, используйте /start.")
        return

    handle_answer(chat_id, text)


def get_updates(offset):
    query = parse.urlencode({"timeout": 30, "offset": offset})
    with request.urlopen(f"{TELEGRAM_API}/getUpdates?{query}", timeout=35) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("result", [])


def main():
    telegram("deleteWebhook", {"drop_pending_updates": True})
    print("Bot started. Press Ctrl+C to stop.")
    offset = None

    while True:
        try:
            for update in get_updates(offset):
                offset = update["update_id"] + 1
                handle_update(update)
        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as exc:
            print(f"Error: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    main()
