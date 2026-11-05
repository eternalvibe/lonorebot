import sqlite3
import re
import telebot
from telebot import types
import os
from pathlib import Path

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен BOT_TOKEN не найден в .env файле!")

# Bothost автоматически задаёт DATA_DIR=/app/data
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "mafia_tournament.db"

ADMIN_IDS = {8595107331, 8025502507, 1955476231}  # UID администраторов
# ===================================

bot = telebot.TeleBot(BOT_TOKEN)


# ---------- Работа с БД ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            team_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            emoji TEXT NOT NULL,
            members TEXT NOT NULL,
            captains TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def team_exists(team_name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM teams WHERE team_name = ? COLLATE NOCASE", (team_name.strip(),))
    row = cur.fetchone()
    conn.close()
    return row is not None


def user_already_registered(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM teams WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def save_team(user_id, team_name, emoji, members, captains):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO teams (user_id, team_name, emoji, members, captains)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, team_name, emoji, members, captains))
    conn.commit()
    conn.close()


def get_all_teams():
    """Возвращает список (id, team_name, emoji, members, captains)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, team_name, emoji, members, captains FROM teams ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_team_by_id(team_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, team_name, emoji, members, captains FROM teams WHERE id = ?",
        (team_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def delete_team(team_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_all_registered_usernames(exclude_team_id: int | None = None) -> set[str]:
    """Возвращает множество занятых юзернеймов (в нижнем регистре, с @)."""
    used = set()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if exclude_team_id is None:
        cur.execute("SELECT members, captains FROM teams")
    else:
        cur.execute(
            "SELECT members, captains FROM teams WHERE id != ?", (exclude_team_id,)
        )
    for members, captains in cur.fetchall():
        for text in (members, captains):
            for m in re.findall(r"@\w+", text):
                used.add(m.lower())
    conn.close()
    return used


# ---------- Хранилище состояний (в памяти) ----------
user_states = {}

WELCOME_TEXT = (
    "👋 Это бот регистрации на турнир.\n"
    "Формат: 5 игроков + 2 запасных, максимум 7 игроков.\n\n"
    "Выберите действие в меню ниже 👇"
)

QUESTION_1 = "1️⃣ Напишите название вашей команды."
QUESTION_2 = (
    "2️⃣ Укажите смайл вашей команды.\n"
    "Примеры: 🗿 🔥 🤡 💦 🧠"
)
QUESTION_3 = (
    "3️⃣ Укажите юзернеймы и никнеймы ваших участников.\n"
    "Формат: @юзернейм — ник (каждый игрок с новой строки)\n"
    "⚠️ На время турнира юзеры просьба не менять, дабы не было путаницы."
)
QUESTION_4 = (
    "4️⃣ Укажите юзернеймы капитана и заместителя капитана.\n"
    "Формат: @юзернейм_капитана, @юзернейм_заместителя"
)


# ---------- Клавиатуры ----------
def main_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.add(types.KeyboardButton("🔐 Зарегистрироваться"))
    kb.add(types.KeyboardButton("📜 Список команд"))
    return kb


def cancel_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


def teams_inline_kb(is_admin: bool) -> types.InlineKeyboardMarkup:
    """Кнопки со списком команд. Для админов под каждой — кнопка удаления."""
    teams = get_all_teams()
    kb = types.InlineKeyboardMarkup(row_width=1)
    if not teams:
        return kb
    for team_id, name, emoji, _, _ in teams:
        kb.add(types.InlineKeyboardButton(
            text=f"{emoji} {name}",
            callback_data=f"view:{team_id}",
        ))
        if is_admin:
            kb.add(types.InlineKeyboardButton(
                text=f"📤 Удалить «{name}»",
                callback_data=f"del:{team_id}",
            ))
    return kb


# ---------- Утилиты ----------
def extract_usernames(text: str) -> list[str]:
    """Возвращает все @username из текста (в нижнем регистре)."""
    return [m.lower() for m in re.findall(r"@\w+", text)]


# ---------- Хендлеры: команды ----------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=main_menu_kb())


@bot.message_handler(commands=["register"])
def cmd_register(message):
    start_registration(message)


@bot.message_handler(commands=["teams"])
def cmd_teams(message):
    show_teams_list(message)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    cancel_registration(message)


# ---------- Хендлеры: текст ----------
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()

    # ---- Кнопки главного меню ----
    if text == "🔐 Зарегистрироваться":
        start_registration(message)
        return
    if text == "📜 Список команд":
        show_teams_list(message)
        return
    if text == "❌ Отмена":
        cancel_registration(message)
        return

    # ---- Пошаговая регистрация ----
    state = user_states.get(user_id)
    if not state:
        bot.send_message(
            message.chat.id,
            "Выберите действие в меню ниже 👇",
            reply_markup=main_menu_kb(),
        )
        return

    step = state["step"]

    # Шаг 1 — название
    if step == 1:
        if len(text) < 2 or len(text) > 50:
            bot.send_message(message.chat.id, "Название должно быть от 2 до 50 символов. Попробуйте ещё раз:",
                             reply_markup=cancel_kb())
            return
        if team_exists(text):
            bot.send_message(
                message.chat.id,
                f"❌ Команда с названием «{text}» уже существует. Введите другое название:",
                reply_markup=cancel_kb(),
            )
            return
        state["data"]["team_name"] = text
        state["step"] = 2
        bot.send_message(message.chat.id, QUESTION_2, reply_markup=cancel_kb())

    # Шаг 2 — смайл
    elif step == 2:
        if len(text) > 10:
            bot.send_message(message.chat.id, "Слишком длинный смайл. Отправьте 1–2 эмодзи:",
                             reply_markup=cancel_kb())
            return
        state["data"]["emoji"] = text
        state["step"] = 3
        bot.send_message(message.chat.id, QUESTION_3, reply_markup=cancel_kb())

    # Шаг 3 — участники
    elif step == 3:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 5 or len(lines) > 7:
            bot.send_message(
                message.chat.id,
                f"Нужно от 5 до 7 участников (у вас {len(lines)}). "
                "Отправьте список заново, каждый игрок с новой строки:",
                reply_markup=cancel_kb(),
            )
            return

        usernames = []
        for ln in lines:
            found = extract_usernames(ln)
            if not found:
                bot.send_message(
                    message.chat.id,
                    f"❌ В строке «{ln}» не найден @юзернейм. "
                    "Каждый участник должен быть в формате: @юзернейм — ник.\n"
                    "Отправьте список заново:",
                    reply_markup=cancel_kb(),
                )
                return
            usernames.extend(found)

        # Дубликаты внутри своей команды
        if len(usernames) != len(set(usernames)):
            bot.send_message(
                message.chat.id,
                "❌ В вашем списке есть повторяющиеся юзернеймы. "
                "Каждый игрок должен быть указан один раз. Отправьте список заново:",
                reply_markup=cancel_kb(),
            )
            return

        # Пересечения с уже зарегистрированными командами
        used_elsewhere = get_all_registered_usernames()
        clash = [u for u in set(usernames) if u in used_elsewhere]
        if clash:
            bot.send_message(
                message.chat.id,
                "❌ Следующие юзернеймы уже участвуют в других командах:\n"
                + "\n".join(clash)
                + "\n\nИгрок не может быть в двух командах. Отправьте список заново:",
                reply_markup=cancel_kb(),
            )
            return

        state["data"]["members"] = text
        state["step"] = 4
        bot.send_message(message.chat.id, QUESTION_4, reply_markup=cancel_kb())

    # Шаг 4 — капитан и зам
    elif step == 4:
        if "," not in text or text.count("@") < 2:
            bot.send_message(
                message.chat.id,
                "Нужно указать двух человек через запятую, формат: @капитан, @зам. Попробуйте ещё раз:",
                reply_markup=cancel_kb(),
            )
            return

        cap_usernames = extract_usernames(text)
        members_usernames = set(extract_usernames(state["data"]["members"]))

        # Капитан и зам должны быть из числа участников
        not_in_team = [u for u in cap_usernames if u not in members_usernames]
        if not_in_team:
            bot.send_message(
                message.chat.id,
                "❌ Эти юзернеймы не найдены среди участников вашей команды:\n"
                + "\n".join(not_in_team)
                + "\n\nКапитан и заместитель должны быть указаны в списке участников. Попробуйте ещё раз:",
                reply_markup=cancel_kb(),
            )
            return

        state["data"]["captains"] = text

        # Финальная проверка названия на дубликат
        if team_exists(state["data"]["team_name"]):
            bot.send_message(
                message.chat.id,
                f"❌ Команда «{state['data']['team_name']}» только что была зарегистрирована другим. "
                "Начните заново: /register",
                reply_markup=main_menu_kb(),
            )
            del user_states[user_id]
            return

        data = state["data"]
        save_team(
            user_id=user_id,
            team_name=data["team_name"],
            emoji=data["emoji"],
            members=data["members"],
            captains=data["captains"],
        )
        del user_states[user_id]

        card = (
            "✅ <b>Карточка команды</b>\n\n"
            f"🏷 Название: <b>{data['team_name']}</b>\n"
            f"🎭 Смайл: {data['emoji']}\n\n"
            f"👥 <b>Участники:</b>\n{data['members']}\n\n"
            f"👑 <b>Капитан и зам:</b>\n{data['captains']}\n\n"
            "🎉 <b>Команда успешно зарегистрирована!</b>"
        )
        bot.send_message(message.chat.id, card, parse_mode="HTML", reply_markup=main_menu_kb())


# ---------- Функции логики ----------
def start_registration(message):
    user_id = message.from_user.id
    if user_already_registered(user_id):
        bot.send_message(
            message.chat.id,
            "❌ Вы уже зарегистрировали команду. Повторная регистрация невозможна.",
            reply_markup=main_menu_kb(),
        )
        return
    user_states[user_id] = {"step": 1, "data": {}}
    bot.send_message(message.chat.id, QUESTION_1, reply_markup=cancel_kb())


def cancel_registration(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        bot.send_message(message.chat.id, "Регистрация отменена.", reply_markup=main_menu_kb())
    else:
        bot.send_message(message.chat.id, "Нечего отменять.", reply_markup=main_menu_kb())


def show_teams_list(message):
    is_admin = message.from_user.id in ADMIN_IDS
    kb = teams_inline_kb(is_admin)
    teams = get_all_teams()
    if not teams:
        bot.send_message(message.chat.id, "Пока нет зарегистрированных команд.",
                         reply_markup=main_menu_kb())
        return
    bot.send_message(
        message.chat.id,
        "📋 <b>Список зарегистрированных команд:</b>\nНажмите на команду, чтобы увидеть состав.",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ---------- Callback-хендлеры (inline-кнопки) ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("view:"))
def cb_view_team(call: types.CallbackQuery):
    team_id = int(call.data.split(":", 1)[1])
    team = get_team_by_id(team_id)
    if not team:
        bot.answer_callback_query(call.id, "Команда не найдена.")
        return
    _, name, emoji, members, captains = team

    members_list = "\n".join(f"• {ln}" for ln in members.split("\n") if ln.strip())
    text = (
        f"{emoji} <b>{name}</b>\n\n"
        f"👥 <b>Участники:</b>\n{members_list}\n\n"
        f"👑 <b>Капитан и зам:</b>\n{captains}"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def cb_delete_team(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔ У вас нет прав на удаление.", show_alert=True)
        return

    team_id = int(call.data.split(":", 1)[1])
    team = get_team_by_id(team_id)
    if not team:
        bot.answer_callback_query(call.id, "Команда уже удалена.")
        return

    _, name, emoji, _, _ = team
    if delete_team(team_id):
        bot.answer_callback_query(call.id, f"Команда «{name}» удалена.")
        # Обновляем список у админа
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=teams_inline_kb(is_admin=True),
            )
        except Exception:
            # Если сообщение старое/нельзя отредактировать — просто пришлём новое
            bot.send_message(
                call.message.chat.id,
                "📋 Обновлённый список команд:",
                reply_markup=teams_inline_kb(is_admin=True),
            )
    else:
        bot.answer_callback_query(call.id, "Не удалось удалить.")


# ---------- Запуск ----------
if __name__ == "__main__":
    init_db()
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    bot.infinity_polling()
