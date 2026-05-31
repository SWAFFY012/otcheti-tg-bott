import os
import re
import json
from collections import deque
from datetime import datetime
from urllib import request as url_request

from flask import Flask, jsonify, request


app = Flask(__name__)

TOKEN = os.environ.get("TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None

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
processed_update_ids = set()
processed_update_order = deque()
MAX_PROCESSED_UPDATES = 200


def is_duplicate_update(update_id):
    if update_id is None:
        return False

    if update_id in processed_update_ids:
        return True

    processed_update_ids.add(update_id)
    processed_update_order.append(update_id)

    while len(processed_update_order) > MAX_PROCESSED_UPDATES:
        old_update_id = processed_update_order.popleft()
        processed_update_ids.discard(old_update_id)

    return False


def send_message(chat_id, text):
    if not TELEGRAM_API:
        raise RuntimeError("TOKEN environment variable is not set")

    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = url_request.Request(
        f"{TELEGRAM_API}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with url_request.urlopen(req, timeout=10) as response:
        response.read()


def start_report(chat_id):
    sessions[chat_id] = {"step": 0, "answers": {}}
    send_message(
        chat_id,
        "Привет! Я помогу создать отчёт Мега Химки.\n"
        f"{FIELDS[0][2]}",
    )


def build_report(answers):
    date_str = datetime.now().strftime("%d.%m.%Y")
    lines = [f"Отчёт Мега Химки {date_str}:"]

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
    message = update.get("message") or update.get("edited_message") or {}
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


@app.route("/api/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}

    if is_duplicate_update(update.get("update_id")):
        return jsonify({"ok": True, "duplicate": True})

    handle_update(update)
    return jsonify({"ok": True})


@app.route("/api/webhook", methods=["GET"])
def webhook_info():
    return jsonify({"ok": True, "status": "webhook is running"})


@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True, "status": "Mega Khimki report bot is running"})
