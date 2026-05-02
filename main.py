# v 3.1 — PostgreSQL

import telebot
import random
import time
import json
import os
import threading
import requests
import psycopg2
from psycopg2.extras import Json

# ====== ОТКЛЮЧЕНИЕ ПРОКСИ ======
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(env_var, None)
telebot.apihelper.proxy = {}

TOKEN = "8683812027:AAHj3BWuLj7o5NqntF7l02STco_N2jL6Vvs"
ADMIN_ID = "6933588930"

# ====== НАСТРОЙКИ БОТА ======
bot = telebot.TeleBot(
    TOKEN,
    threaded=True,
    num_threads=8,
    parse_mode=None
)

# ====== ТРЕЙД-КОМНАТЫ ======
trade_rooms = {}
pending_qty = {}
card_menus = {}

# ====== БЛОКИРОВКА ======
data_lock = threading.Lock()
_save_scheduled = False

# ====== POSTGRESQL ======
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"[ERROR] Не удалось подключиться к БД: {e}")
        return None

def init_db():
    if not DATABASE_URL:
        print("[INFO] DATABASE_URL не найден, используем локальный JSON")
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_data (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL DEFAULT '{}'
            )
        """)
        cur.execute("""
            INSERT INTO bot_data (key, value)
            VALUES ('users', '{}')
            ON CONFLICT (key) DO NOTHING
        """)
        conn.commit()
        print("[OK] База данных инициализирована")
    except Exception as e:
        print(f"[ERROR] Ошибка инициализации БД: {e}")
    finally:
        conn.close()

def load_data():
    if not DATABASE_URL:
        if os.path.exists("users.json"):
            try:
                with open("users.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"[OK] Загружено {len(data)} пользователей из users.json")
                    return data
            except Exception as e:
                print(f"[ERROR] Ошибка загрузки JSON: {e}")
        return {}

    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_data WHERE key = 'users'")
        row = cur.fetchone()
        if row:
            data = row[0]
            print(f"[OK] Загружено {len(data)} пользователей из PostgreSQL")
            return data
        return {}
    except Exception as e:
        print(f"[ERROR] Ошибка загрузки из БД: {e}")
        return {}
    finally:
        conn.close()

def save_data():
    with data_lock:
        if not DATABASE_URL:
            try:
                tmp_file = "users.json.tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=4, ensure_ascii=False)
                os.replace(tmp_file, "users.json")
                print(f"[OK] Сохранено {len(users)} пользователей в users.json")
            except IOError as e:
                print(f"[ERROR] Ошибка сохранения JSON: {e}")
            return

        conn = get_db_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO bot_data (key, value)
                VALUES ('users', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (Json(users),))
            conn.commit()
            print(f"[OK] Сохранено {len(users)} пользователей в PostgreSQL")
        except Exception as e:
            print(f"[ERROR] Ошибка сохранения в БД: {e}")
        finally:
            conn.close()

def schedule_save():
    global _save_scheduled
    if not _save_scheduled:
        _save_scheduled = True
        def _do_save():
            global _save_scheduled
            time.sleep(3)
            save_data()
            _save_scheduled = False
        threading.Thread(target=_do_save, daemon=True).start()

# ====== ИНИЦИАЛИЗАЦИЯ ======
init_db()
users = load_data()

def fix_inventory(user):
    if isinstance(user["inventory"], list):
        new_inv = {}
        for item in user["inventory"]:
            new_inv[item] = new_inv.get(item, 0) + 1
        user["inventory"] = new_inv

def get_user(user_id, tg_user=None):
    user_id = str(user_id)
    changed = False

    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "inventory": {},
            "last_open": 0,
            "opens": 0,
            "captcha": False,
            "username": None,
            "first_name": None
        }
        changed = True

    u = users[user_id]

    if tg_user is not None:
        new_username = tg_user.username or None
        new_first = tg_user.first_name or None
        if u.get("username") != new_username or u.get("first_name") != new_first:
            u["username"] = new_username
            u["first_name"] = new_first
            changed = True

    for field, default in [("username", None), ("first_name", None), ("opens", 0)]:
        if field not in u:
            u[field] = default
            changed = True

    fix_inventory(u)

    if changed:
        schedule_save()

    return u

def get_display_name(uid):
    u = users.get(str(uid), {})
    return u.get("first_name") or f"Игрок {uid}"

# ====== КАРТЫ ======
cards = [
    {"name": "ирина владимировна",    "rarity": "common",    "chance": 1/2},
    {"name": "елена олеговна",         "rarity": "common",    "chance": 1/3},
    {"name": "сергей коваленко",       "rarity": "common",    "chance": 1/4},
    {"name": "юрий николаевич",        "rarity": "common",    "chance": 1/6},
    {"name": "виталий андреевич",      "rarity": "common",    "chance": 1/8},
    {"name": "александр анатольевич",  "rarity": "rare",      "chance": 1/10},
    {"name": "анна николаевна",        "rarity": "rare",      "chance": 1/12},
    {"name": "богдашевская",           "rarity": "rare",      "chance": 1/15},
    {"name": "овсянников",             "rarity": "rare",      "chance": 1/17},
    {"name": "алена игоревна",         "rarity": "epic",      "chance": 1/20},
    {"name": "ольга виталиевна",       "rarity": "epic",      "chance": 1/24},
    {"name": "наталия валериевна",     "rarity": "epic",      "chance": 1/30},
    {"name": "оксана ивановна",        "rarity": "epic",      "chance": 1/34},
    {"name": "виктор викентиевич",     "rarity": "mythic",    "chance": 1/40},
    {"name": "вера федоровна",         "rarity": "mythic",    "chance": 1/55},
    {"name": "татьяна леонидовна",     "rarity": "mythic",    "chance": 1/75},
    {"name": "людмила",                "rarity": "legendary", "chance": 1/100},
    {"name": "мунтяну",                "rarity": "legendary", "chance": 1/150},
    {"name": "ирина григориевна",      "rarity": "legendary", "chance": 1/215},
    {"name": "наталия технолоджия",    "rarity": "exotic",    "chance": 1/350},
    {"name": "барабаш",                "rarity": "exotic",    "chance": 1/750},
    {"name": "дмитро",                 "rarity": "secret",    "chance": 1/5000},
    {"name": "брудин",                 "rarity": "secret",    "chance": 1/12500},
    {"name": "БudkО",                  "rarity": "glitch",    "chance": 1/50000},
]

CARD_GENDER = {
    "ирина владимировна":    "f",
    "елена олеговна":        "f",
    "сергей коваленко":      "m",
    "юрий николаевич":       "m",
    "виталий андреевич":     "m",
    "александр анатольевич": "m",
    "анна николаевна":       "f",
    "богдашевская":          "f",
    "овсянников":            "m",
    "алена игоревна":        "f",
    "ольга виталиевна":      "f",
    "наталия валериевна":    "f",
    "оксана ивановна":       "f",
    "виктор викентиевич":    "m",
    "вера федоровна":        "f",
    "татьяна леонидовна":    "f",
    "людмила":               "f",
    "мунтяну":               "f",
    "ирина григориевна":     "f",
    "наталия технолоджия":   "f",
    "барабаш":               "m",
    "дмитро":                "m",
    "брудин":                "m",
    "БudkО":                 "f",
}

RARITY_NAMES_GENDER = {
    "common":    {"m": "Обычный",       "f": "Обычная"},
    "rare":      {"m": "Редкий",        "f": "Редкая"},
    "epic":      {"m": "Эпический",     "f": "Эпическая"},
    "mythic":    {"m": "Мифический",    "f": "Мифическая"},
    "legendary": {"m": "Легендарный",   "f": "Легендарная"},
    "exotic":    {"m": "Экзотический",  "f": "Экзотическая"},
    "secret":    {"m": "Секретный",     "f": "Секретная"},
    "glitch":    {"m": "ГЛИТЧ",         "f": "ГЛИТЧ"},
}

RARITY_ORDER = {
    "common": 0, "rare": 1, "epic": 2, "mythic": 3,
    "legendary": 4, "exotic": 5, "secret": 6, "glitch": 7,
}

CARD_TYPE_ORDER = {"normal": 0, "gold": 1, "rainbow": 2}

RARITY_EMOJI = {
    "common":    "⚪",
    "rare":      "🔵",
    "epic":      "🟣",
    "mythic":    "🔴",
    "legendary": "🟡",
    "exotic":    "🟠",
    "secret":    "💎",
    "glitch":    "👾",
}

RARITY_NAMES = {
    "common":    "Обычная",
    "rare":      "Редкая",
    "epic":      "Эпик",
    "mythic":    "Мифик",
    "legendary": "Легендарная",
    "exotic":    "Экзотик",
    "secret":    "Секретная",
    "glitch":    "ГЛИТЧ",
}

COOLDOWN = 3

# ====== ПУЛ КАРТ ======
_card_pool = []
_pool_total = 0

def _build_card_pool():
    global _card_pool, _pool_total
    pool = []
    for card in cards:
        base_weight = card["chance"]
        base_x = int(1 / base_weight)
        base_name = f"{card['name']}-{card['rarity']}"
        pool.append({
            "name": base_name,
            "weight": base_weight,
            "min_reward": base_x,
            "max_reward": base_x * 7
        })
        pool.append({
            "name": f"{base_name}-gold",
            "weight": base_weight / 5,
            "min_reward": base_x * 2,
            "max_reward": base_x * 10
        })
        pool.append({
            "name": f"{base_name}-rainbow",
            "weight": base_weight / 10,
            "min_reward": base_x * 3,
            "max_reward": base_x * 15
        })
    _card_pool = pool
    _pool_total = sum(c["weight"] for c in pool)

_build_card_pool()

def parse_card(card_name):
    parts = card_name.split("-")
    rarity_type = parts[-1] if parts[-1] in ["gold", "rainbow"] else "normal"
    return parts[0], rarity_type

def get_card_rarity(card_key):
    parts = card_key.split("-")
    if parts[-1] in ["gold", "rainbow"]:
        return parts[-2] if len(parts) >= 3 else "common"
    return parts[-1] if len(parts) >= 2 else "common"

def get_card_type(card_key):
    parts = card_key.split("-")
    return parts[-1] if parts[-1] in ["gold", "rainbow"] else "normal"

def format_card_name(card_key, rarity_type):
    base = card_key.split("-")[0]
    gender = CARD_GENDER.get(base, "m")
    prefix = ""
    if rarity_type == "gold":
        prefix = "Золотая" if gender == "f" else "Золотой"
    elif rarity_type == "rainbow":
        prefix = "Радужная" if gender == "f" else "Радужный"
    return f"{prefix} {base}" if prefix else base.capitalize()

def get_random_card():
    r = random.uniform(0, _pool_total)
    upto = 0.0
    for c in _card_pool:
        upto += c["weight"]
        if upto >= r:
            result = dict(c)
            result["reward"] = random.randint(int(c["min_reward"]), int(c["max_reward"]))
            return result
    c = _card_pool[-1]
    result = dict(c)
    result["reward"] = random.randint(int(c["min_reward"]), int(c["max_reward"]))
    return result

# ====== ИНВЕНТАРЬ ======

def sort_inventory(inventory, sort_by="rarity_desc"):
    items = list(inventory.items())
    if sort_by == "rarity_desc":
        items.sort(key=lambda x: (
            RARITY_ORDER.get(get_card_rarity(x[0]), 0),
            CARD_TYPE_ORDER.get(get_card_type(x[0]), 0)
        ), reverse=True)
    elif sort_by == "rarity_asc":
        items.sort(key=lambda x: (
            RARITY_ORDER.get(get_card_rarity(x[0]), 0),
            CARD_TYPE_ORDER.get(get_card_type(x[0]), 0)
        ))
    elif sort_by == "count_desc":
        items.sort(key=lambda x: x[1], reverse=True)
    elif sort_by == "name":
        items.sort(key=lambda x: x[0])
    return items

def inventory_text(inventory, sort_by="rarity_desc"):
    if not inventory:
        return "🎒 Инвентарь пуст"
    items = sort_inventory(inventory, sort_by)
    lines = ["🎒 <b>Твои карты:</b>\n"]
    for card, count in items:
        name, rarity_type = parse_card(card)
        display = format_card_name(card, rarity_type)
        rarity = get_card_rarity(card)
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        rname = RARITY_NAMES.get(rarity, rarity)
        lines.append(f"{emoji} <b>{display}</b>  <i>{rname}</i>  ×{count}")
    return "\n".join(lines)

def inventory_keyboard(sort_by="rarity_desc"):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    sorts = [
        ("rarity_desc", "🏆 Редкость ↓"),
        ("rarity_asc",  "🏆 Редкость ↑"),
        ("count_desc",  "📊 Кол-во ↓"),
        ("name",        "🔤 По имени"),
    ]
    btns = [
        telebot.types.InlineKeyboardButton(
            f"✅ {label}" if sort_by == key else label,
            callback_data=f"invsort_{key}"
        )
        for key, label in sorts
    ]
    kb.add(*btns)
    return kb

# ====== ТАБЛИЦА ЛИДЕРОВ ======

def leaderboard_text(sort_by="balance"):
    if sort_by == "balance":
        ranked = sorted(users.items(), key=lambda x: x[1].get("balance", 0), reverse=True)
        title = "💰 Топ по шейк-коинам"
    else:
        ranked = sorted(users.items(), key=lambda x: x[1].get("opens", 0), reverse=True)
        title = "📦 Топ по открытым боксам"

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>{title}</b>\n"]

    for i, (uid, data) in enumerate(ranked[:10]):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = get_display_name(uid)
        value = (
            f"{data.get('balance', 0)} 💰"
            if sort_by == "balance"
            else f"{data.get('opens', 0)} 📦"
        )
        lines.append(f"{medal} {name} — {value}")

    if not ranked:
        lines.append("Пока никого нет...")
    return "\n".join(lines)

def leaderboard_keyboard(sort_by="balance"):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(
            "✅ 💰 По коинам" if sort_by == "balance" else "💰 По коинам",
            callback_data="lb_balance"
        ),
        telebot.types.InlineKeyboardButton(
            "✅ 📦 По боксам" if sort_by == "boxes" else "📦 По боксам",
            callback_data="lb_boxes"
        )
    )
    return kb

# ====== МЕНЮ ======

def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📦 Открыть бокс")
    markup.add("💰 Баланс", "🎒 Инвентарь")
    markup.add("🏠 Трейд", "🏆 Лидеры")
    markup.add("📊 Редкости", "📢 Канал")
    return markup

# ====== ОБРАБОТЧИКИ ======

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.from_user.id, msg.from_user)
    bot.send_message(msg.chat.id, "Добро пожаловать в Тичер Боксы!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "💰 Баланс")
def balance(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    bot.send_message(
        msg.chat.id,
        f"💰 Баланс: {user['balance']}\n📦 Открыто боксов: {user.get('opens', 0)}"
    )

@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def inventory(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    if not user["inventory"]:
        bot.send_message(msg.chat.id, "🎒 Инвентарь пуст")
        return
    sort_by = "rarity_desc"
    bot.send_message(
        msg.chat.id,
        inventory_text(user["inventory"], sort_by),
        reply_markup=inventory_keyboard(sort_by),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("invsort_"))
def inv_sort_cb(call):
    sort_by = call.data.split("_", 1)[1]
    uid = str(call.from_user.id)
    user = get_user(uid, call.from_user)
    if not user["inventory"]:
        bot.answer_callback_query(call.id, "Инвентарь пуст")
        return
    text = inventory_text(user["inventory"], sort_by)
    kb = inventory_keyboard(sort_by)
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.text == "🏆 Лидеры")
def leaders(msg):
    get_user(msg.from_user.id, msg.from_user)
    sort_by = "balance"
    bot.send_message(
        msg.chat.id,
        leaderboard_text(sort_by),
        reply_markup=leaderboard_keyboard(sort_by),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("lb_"))
def lb_switch_cb(call):
    sort_by = "balance" if call.data == "lb_balance" else "boxes"
    text = leaderboard_text(sort_by)
    kb = leaderboard_keyboard(sort_by)
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# ====== ОТКРЫТИЕ БОКСА ======

@bot.message_handler(func=lambda m: m.text == "📦 Открыть бокс")
def open_box(msg):
    user = get_user(msg.from_user.id, msg.from_user)

    if user["captcha"]:
        bot.send_message(msg.chat.id, "Напиши: Я не робот")
        return

    remaining = COOLDOWN - (time.time() - user["last_open"])
    if remaining > 0:
        bot.send_message(msg.chat.id, f"⏳ Подожди {remaining:.1f} секунды!")
        return

    user["last_open"] = time.time()
    user["opens"] = user.get("opens", 0) + 1

    if user["opens"] % random.randint(50, 100) == 0:
        user["captcha"] = True
        schedule_save()
        bot.send_message(msg.chat.id, "🤖 Напиши: Я не робот")
        return

    card = get_random_card()
    user["inventory"][card["name"]] = user["inventory"].get(card["name"], 0) + 1
    user["balance"] += card["reward"]
    schedule_save()

    rarity_type = (
        "rainbow" if "-rainbow" in card["name"]
        else "gold" if "-gold" in card["name"]
        else "normal"
    )

    base_name = card["name"].split("-")[0]
    rarity = get_card_rarity(card["name"])
    gender = CARD_GENDER.get(base_name, "m")

    clean_name = format_card_name(card["name"], rarity_type)
    emoji = RARITY_EMOJI.get(rarity, "⚪")
    rname = RARITY_NAMES_GENDER.get(rarity, {}).get(gender, rarity)

    text = f"{emoji} <b>{clean_name}</b>\n<i>{rname}</i>\n\n+{card['reward']} 💰"

    if rarity_type in ("gold", "rainbow"):
        img_paths = [
            f"cards/{base_name}-{rarity}-{rarity_type}.png",
            f"cards/{base_name}-{rarity}.png",
        ]
    else:
        img_paths = [f"cards/{base_name}-{rarity}.png"]

    sent = False
    for img_path in img_paths:
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as img:
                    bot.send_photo(msg.chat.id, img, caption=text, parse_mode="HTML")
                sent = True
                break
            except Exception as e:
                print(f"[WARN] Не удалось отправить фото {img_path}: {e}")

    if not sent:
        bot.send_message(msg.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: users.get(str(m.from_user.id), {}).get("captcha") is True)
def captcha_check(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    if msg.text and msg.text.lower() == "я не робот":
        user["captcha"] = False
        schedule_save()
        bot.send_message(msg.chat.id, "✅ Проверка пройдена!")
    else:
        bot.send_message(msg.chat.id, "❌ Напиши: Я не робот")

@bot.message_handler(func=lambda m: m.text == "📊 Редкости")
def show_rarities(msg):
    get_user(msg.from_user.id, msg.from_user)
    lines = ["🎴 <b>Редкости карт:</b>\n"]
    for rarity in ["common", "rare", "epic", "mythic", "legendary", "exotic", "secret", "glitch"]:
        emoji = RARITY_EMOJI[rarity]
        rname = RARITY_NAMES[rarity]
        lines.append(f"{emoji} <b>{rname}</b>")
    lines.append("\n🌕 <b>Золотая</b> — шанс в 5 раз меньше обычной")
    lines.append("🌈 <b>Радужная</b> — шанс в 10 раз меньше обычной")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📢 Канал")
def show_channel(msg):
    get_user(msg.from_user.id, msg.from_user)
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton(
        "📢 Перейти в канал",
        url="https://t.me/+HltU54rHvwZmMjdi"
    ))
    bot.send_message(
        msg.chat.id,
        "📢 <b>Наш Telegram канал</b>\n\nПодписывайся, чтобы не пропустить новости и обновления!",
        reply_markup=kb,
        parse_mode="HTML"
    )

# ══════════════════════════════════════════════
#               ТОРГОВЛЯ
# ══════════════════════════════════════════════

def trade_text(code):
    room = trade_rooms[code]

    def fmt_items(items):
        if not items:
            return "  (ничего)"
        return "\n".join(
            f"  {RARITY_EMOJI.get(get_card_rarity(k), '⚪')} "
            f"{format_card_name(k, parse_card(k)[1])} ×{v}"
            for k, v in items.items()
        )

    owner_ready = "✅" if room["owner_ready"] else "⏳"
    guest_ready = "✅" if room["guest_ready"] else "⏳"
    owner_name = get_display_name(room["owner"])
    guest_label = (
        "ожидание игрока..."
        if room["guest"] is None
        else f"{get_display_name(room['guest'])} {guest_ready}"
    )

    return (
        f"🔄 <b>ТРЕЙД</b>  |  код: <code>{code}</code>\n\n"
        f"🟦 {owner_name} {owner_ready}\n{fmt_items(room['owner_items'])}\n\n"
        f"🟥 {guest_label}\n{fmt_items(room['guest_items'])}"
    )

def trade_keyboard(code, uid):
    room = trade_rooms[code]
    uid = str(uid)
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    is_owner = uid == room["owner"]
    is_guest = uid == room["guest"]

    if is_owner or is_guest:
        side = "owner" if is_owner else "guest"
        ready = room["owner_ready"] if is_owner else room["guest_ready"]
        kb.add(
            telebot.types.InlineKeyboardButton(
                "➕ Добавить карту", callback_data=f"tinv_{code}_{side}"
            ),
            telebot.types.InlineKeyboardButton(
                "➖ Убрать карту", callback_data=f"tremove_{code}_{side}"
            )
        )
        ready_label = "❌ Не готов" if ready else "✅ Готов"
        kb.add(telebot.types.InlineKeyboardButton(
            ready_label, callback_data=f"tready_{code}_{side}"
        ))

    kb.add(telebot.types.InlineKeyboardButton(
        "🚫 Отменить", callback_data=f"tcancel_{code}"
    ))
    return kb

def send_trade_to(code, uid, chat_id, edit=False):
    room = trade_rooms[code]
    text = trade_text(code)
    kb = trade_keyboard(code, uid)
    msg_key = "owner_msg" if str(uid) == room["owner"] else "guest_msg"

    if edit and room.get(msg_key):
        try:
            bot.edit_message_text(
                text, chat_id, room[msg_key],
                reply_markup=kb, parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        sent = bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
        room[msg_key] = sent.message_id

def refresh_trade(code):
    room = trade_rooms.get(code)
    if not room:
        return
    send_trade_to(code, room["owner"], room["owner_chat"], edit=True)
    if room["guest"] and room.get("guest_chat"):
        send_trade_to(code, room["guest"], room["guest_chat"], edit=True)

def close_trade(code, result_text):
    if code not in trade_rooms:
        return
    room = trade_rooms[code]
    for chat_id, msg_id in [
        (room["owner_chat"], room.get("owner_msg")),
        (room.get("guest_chat"), room.get("guest_msg")),
    ]:
        if chat_id and msg_id:
            try:
                bot.edit_message_text(result_text, chat_id, msg_id)
            except Exception:
                pass
    del trade_rooms[code]

def check_items_available(user_inv, items):
    return all(user_inv.get(card, 0) >= count for card, count in items.items())

@bot.message_handler(func=lambda m: m.text == "🏠 Трейд")
def create_trade(msg):
    uid = str(msg.from_user.id)
    user = get_user(uid, msg.from_user)

    if not user["inventory"]:
        bot.send_message(msg.chat.id, "❌ У тебя нет карт для трейда!")
        return

    for code, room in trade_rooms.items():
        if room["owner"] == uid or room["guest"] == uid:
            bot.send_message(
                msg.chat.id,
                f"⚠️ Ты уже в трейде (код {code}). Сначала отмени его."
            )
            return

    code = str(random.randint(100000, 999999))
    trade_rooms[code] = {
        "owner": uid,
        "guest": None,
        "owner_items": {},
        "guest_items": {},
        "owner_ready": False,
        "guest_ready": False,
        "owner_chat": msg.chat.id,
        "guest_chat": None,
        "owner_msg": None,
        "guest_msg": None,
    }

    bot.send_message(
        msg.chat.id,
        f"🏠 Трейд создан!\n🔑 Код: <b>{code}</b>\n\n"
        f"Отправь код другому игроку — он введёт его в чате со мной.",
        parse_mode="HTML"
    )
    send_trade_to(code, uid, msg.chat.id)

@bot.message_handler(func=lambda m: m.text and m.text.isdigit() and len(m.text) == 6)
def join_trade(msg):
    code = msg.text
    uid = str(msg.from_user.id)

    if code not in trade_rooms:
        bot.send_message(msg.chat.id, "❌ Трейд с таким кодом не найден.")
        return

    room = trade_rooms[code]

    if room["owner"] == uid:
        bot.send_message(msg.chat.id, "⚠️ Это твой собственный трейд.")
        return

    if room["guest"] is not None:
        bot.send_message(msg.chat.id, "❌ Трейд уже занят.")
        return

    for c, r in trade_rooms.items():
        if c != code and (r["owner"] == uid or r["guest"] == uid):
            bot.send_message(msg.chat.id, "⚠️ Ты уже участвуешь в другом трейде.")
            return

    user = get_user(uid, msg.from_user)
    if not user["inventory"]:
        bot.send_message(msg.chat.id, "❌ У тебя нет карт — нечего предложить в трейде.")
        return

    room["guest"] = uid
    room["guest_chat"] = msg.chat.id

    bot.send_message(msg.chat.id, f"✅ Ты вошёл в трейд {code}!")
    send_trade_to(code, uid, msg.chat.id)
    refresh_trade(code)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tinv_"))
def choose_card_to_add(call):
    _, code, side = call.data.split("_", 2)
    uid = str(call.from_user.id)
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд не найден")
        return
    if (side == "owner" and uid != room["owner"]) or \
       (side == "guest" and uid != room["guest"]):
        bot.answer_callback_query(call.id, "Это не твои кнопки")
        return

    user = get_user(uid)
    if not user["inventory"]:
        bot.answer_callback_query(call.id, "Инвентарь пуст")
        return

    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    menu_cards = []
    kb = telebot.types.InlineKeyboardMarkup()

    for card, count in sort_inventory(user["inventory"], "rarity_desc"):
        already = current_offers.get(card, 0)
        available = count - already
        if available <= 0:
            continue
        name, rtype = parse_card(card)
        display = format_card_name(card, rtype)
        rarity = get_card_rarity(card)
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        idx = len(menu_cards)
        menu_cards.append({"card": card, "available": available, "code": code, "side": side})
        kb.add(telebot.types.InlineKeyboardButton(
            f"{emoji} {display}  (есть: {available})",
            callback_data=f"tpick_{uid}_{idx}"
        ))

    if not menu_cards:
        bot.answer_callback_query(call.id, "Нет доступных карт")
        return

    card_menus[uid] = menu_cards
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🎒 Выбери карту для трейда:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tpick_"))
def pick_card(call):
    parts = call.data.split("_")
    uid = str(call.from_user.id)

    if len(parts) != 3 or not parts[2].isdigit():
        bot.answer_callback_query(call.id, "Некорректные данные")
        return

    if uid != parts[1]:
        bot.answer_callback_query(call.id, "Это не твоё меню")
        return

    idx = int(parts[2])
    menu = card_menus.get(uid)
    if not menu or idx >= len(menu):
        bot.answer_callback_query(call.id, "Меню устарело, нажми ➕ снова")
        return

    entry = menu[idx]
    card, code, side = entry["card"], entry["code"], entry["side"]
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд не найден")
        return

    user = get_user(uid)
    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    already = current_offers.get(card, 0)
    available = user["inventory"].get(card, 0) - already

    if available <= 0:
        bot.answer_callback_query(call.id, "Недостаточно карт")
        return

    if available == 1:
        current_offers[card] = already + 1
        if side == "owner":
            room["owner_ready"] = False
        else:
            room["guest_ready"] = False
        bot.answer_callback_query(call.id, "✅ Добавлено")
        refresh_trade(code)
    else:
        pending_qty[uid] = {"code": code, "card": card, "side": side}
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            f"Сколько штук добавить? (доступно: {available})\nНапиши число:"
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("tremove_"))
def choose_card_to_remove(call):
    _, code, side = call.data.split("_", 2)
    uid = str(call.from_user.id)
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд не найден")
        return

    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    if not current_offers:
        bot.answer_callback_query(call.id, "Нечего убирать")
        return

    drop_menu = []
    kb = telebot.types.InlineKeyboardMarkup()
    for card, count in current_offers.items():
        name, rtype = parse_card(card)
        display = format_card_name(card, rtype)
        rarity = get_card_rarity(card)
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        idx = len(drop_menu)
        drop_menu.append({"card": card, "code": code, "side": side})
        kb.add(telebot.types.InlineKeyboardButton(
            f"➖ {emoji} {display} ×{count}",
            callback_data=f"tdrop_{uid}_{idx}"
        ))

    card_menus[f"drop_{uid}"] = drop_menu
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Выбери карту для удаления:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tdrop_"))
def drop_card(call):
    parts = call.data.split("_")
    uid = str(call.from_user.id)

    if len(parts) != 3 or not parts[2].isdigit():
        bot.answer_callback_query(call.id, "Некорректные данные")
        return

    if uid != parts[1]:
        bot.answer_callback_query(call.id, "Это не твоё меню")
        return

    idx = int(parts[2])
    menu = card_menus.get(f"drop_{uid}")
    if not menu or idx >= len(menu):
        bot.answer_callback_query(call.id, "Меню устарело, нажми ➖ снова")
        return

    entry = menu[idx]
    card, code, side = entry["card"], entry["code"], entry["side"]
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд не найден")
        return

    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    if card not in current_offers:
        bot.answer_callback_query(call.id, "Карта не найдена")
        return

    del current_offers[card]
    if side == "owner":
        room["owner_ready"] = False
    else:
        room["guest_ready"] = False

    bot.answer_callback_query(call.id, "✅ Убрано")
    refresh_trade(code)

@bot.message_handler(func=lambda m: str(m.from_user.id) in pending_qty)
def handle_qty_input(msg):
    uid = str(msg.from_user.id)
    if not msg.text or not msg.text.isdigit():
        bot.send_message(msg.chat.id, "❌ Введи целое число")
        return

    qty = int(msg.text)
    info = pending_qty.pop(uid)
    code, card, side = info["code"], info["card"], info["side"]
    room = trade_rooms.get(code)
    if not room:
        bot.send_message(msg.chat.id, "❌ Трейд уже не существует")
        return

    user = get_user(uid)
    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    already = current_offers.get(card, 0)
    available = user["inventory"].get(card, 0) - already

    if qty <= 0 or qty > available:
        bot.send_message(msg.chat.id, f"❌ Некорректное количество (max: {available})")
        return

    current_offers[card] = already + qty
    if side == "owner":
        room["owner_ready"] = False
    else:
        room["guest_ready"] = False

    bot.send_message(msg.chat.id, "✅ Добавлено!")
    refresh_trade(code)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tready_"))
def toggle_ready(call):
    _, code, side = call.data.split("_", 2)
    uid = str(call.from_user.id)
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд не найден")
        return

    if room["guest"] is None:
        bot.answer_callback_query(call.id, "Ожидаем второго игрока")
        return

    current_offers = room["owner_items"] if side == "owner" else room["guest_items"]
    if not current_offers:
        bot.answer_callback_query(call.id, "Добавь хотя бы одну карту")
        return

    if side == "owner":
        room["owner_ready"] = not room["owner_ready"]
    else:
        room["guest_ready"] = not room["guest_ready"]

    bot.answer_callback_query(call.id)

    if room["owner_ready"] and room["guest_ready"]:
        _execute_trade(code)
    else:
        refresh_trade(code)

def _execute_trade(code):
    room = trade_rooms[code]
    owner = get_user(room["owner"])
    guest = get_user(room["guest"])

    if not check_items_available(owner["inventory"], room["owner_items"]):
        close_trade(code, "❌ Трейд отменён: у Игрока 1 не хватает карт.")
        return

    if not check_items_available(guest["inventory"], room["guest_items"]):
        close_trade(code, "❌ Трейд отменён: у Игрока 2 не хватает карт.")
        return

    for card, count in room["owner_items"].items():
        owner["inventory"][card] -= count
        if owner["inventory"][card] <= 0:
            del owner["inventory"][card]
        guest["inventory"][card] = guest["inventory"].get(card, 0) + count

    for card, count in room["guest_items"].items():
        guest["inventory"][card] -= count
        if guest["inventory"][card] <= 0:
            del guest["inventory"][card]
        owner["inventory"][card] = owner["inventory"].get(card, 0) + count

    save_data()
    close_trade(code, "🤝 ТРЕЙД ЗАВЕРШЁН УСПЕШНО!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("tcancel_"))
def cancel_trade(call):
    code = call.data.split("_")[1]
    uid = str(call.from_user.id)
    room = trade_rooms.get(code)
    if not room:
        bot.answer_callback_query(call.id, "Трейд уже не существует")
        return

    if uid != room["owner"] and uid != room["guest"]:
        bot.answer_callback_query(call.id, "Это не твой трейд")
        return

    bot.answer_callback_query(call.id)
    close_trade(code, "🚫 Трейд отменён.")

# ====== ГЛОБАЛЬНОЕ СООБЩЕНИЕ ======
@bot.message_handler(commands=['global'])
def global_message(msg):
    if str(msg.from_user.id) != ADMIN_ID:
        bot.send_message(msg.chat.id, "❌ У тебя нет прав для этой команды.")
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(msg.chat.id, "❌ Напиши сообщение после команды.\nПример: /global Привет всем!")
        return

    text = parts[1].strip()
    total = len(users)
    success = 0
    failed = 0

    bot.send_message(msg.chat.id, f"📤 Отправляю сообщение {total} пользователям...")

    for uid in list(users.keys()):
        try:
            bot.send_message(
                uid,
                f"📢 <b>Сообщение от администратора:</b>\n\n{text}",
                parse_mode="HTML"
            )
            success += 1
            time.sleep(0.05)
        except Exception as e:
            print(f"[WARN] Не удалось отправить {uid}: {e}")
            failed += 1

    bot.send_message(
        msg.chat.id,
        f"✅ Рассылка завершена!\n\n"
        f"📨 Отправлено: {success}\n"
        f"❌ Не доставлено: {failed}"
    )

# ====== ВЫДАТЬ КОИНЫ/БОКСЫ ======
@bot.message_handler(commands=['give'])
def give_coins(msg):
    if str(msg.from_user.id) != ADMIN_ID:
        bot.send_message(msg.chat.id, "❌ У тебя нет прав для этой команды.")
        return

    parts = msg.text.split()

    if len(parts) < 4:
        bot.send_message(
            msg.chat.id,
            "❌ Неверный формат.\n\n"
            "<b>Примеры:</b>\n"
            "/give @username 1000 coins\n"
            "/give 123456789 5 boxes\n"
            "/give @username 500 coins 10 boxes",
            parse_mode="HTML"
        )
        return

    target = parts[1]
    coins_to_give = 0
    boxes_to_give = 0

    i = 2
    while i < len(parts):
        try:
            amount = int(parts[i])
            if i + 1 < len(parts):
                type_ = parts[i + 1].lower()
                if type_ in ['coin', 'coins', 'shk']:
                    coins_to_give = amount
                    i += 2
                elif type_ in ['box', 'boxes']:
                    boxes_to_give = amount
                    i += 2
                else:
                    i += 1
            else:
                i += 1
        except ValueError:
            i += 1

    if coins_to_give == 0 and boxes_to_give == 0:
        bot.send_message(msg.chat.id, "❌ Укажи количество коинов или боксов.")
        return

    target_id = None
    target_name = None

    if target.startswith('@'):
        username = target[1:].lower()
        for uid, data in users.items():
            if (data.get('username') or '').lower() == username:
                target_id = uid
                target_name = data.get('first_name', username)
                break
    else:
        if target in users:
            target_id = target
            target_name = users[target].get('first_name', target)

    if not target_id:
        bot.send_message(msg.chat.id, f"❌ Пользователь {target} не найден в базе.")
        return

    user = get_user(target_id)
    if coins_to_give != 0:
        user['balance'] += coins_to_give
    if boxes_to_give != 0:
        user['opens'] = user.get('opens', 0) + boxes_to_give

    save_data()

    result_parts = []
    if coins_to_give != 0:
        result_parts.append(f"{coins_to_give:+d} 💰")
    if boxes_to_give != 0:
        result_parts.append(f"{boxes_to_give:+d} 📦")

    result = " и ".join(result_parts)

    bot.send_message(msg.chat.id, f"✅ Выдано {target_name} ({target}):\n{result}")

    try:
        bot.send_message(
            target_id,
            f"🎁 <b>Тебе начислено:</b>\n{result}",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ====== ЗАПУСК ======
if __name__ == "__main__":
    print("Удаляем webhook...")
    bot.delete_webhook(drop_pending_updates=True)
    print("Webhook удалён. Бот запущен!")
    while True:
        try:
            bot.polling(
                none_stop=True,
                timeout=20,
                interval=0,
                long_polling_timeout=20
            )
        except requests.exceptions.RequestException as e:
            print(f"\n[!] Сетевая ошибка: {e}")
            time.sleep(15)
        except Exception as e:
            print(f"\n[!] Критическая ошибка: {e}")
            bot.delete_webhook(drop_pending_updates=True)
            time.sleep(15)
