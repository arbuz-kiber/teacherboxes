import json
import psycopg2
from psycopg2.extras import Json
import os

# Вставь свой DATABASE_URL
DATABASE_URL = "postgresql://postgres:EJpttWgvQlrSsBPvrLToKEnyABXiqtuy@postgres.railway.internal:5432/railway"

def import_users():
    # Загружаем users.json
    if not os.path.exists("users.json"):
        print("❌ Файл users.json не найден!")
        return

    with open("users.json", "r", encoding="utf-8") as f:
        users = json.load(f)

    print(f"📂 Загружено {len(users)} пользователей из users.json")

    # Подключаемся к PostgreSQL
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Создаём таблицу если нет
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_data (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{}'
        )
    """)

    # Загружаем текущие данные из БД
    cur.execute("SELECT value FROM bot_data WHERE key = 'users'")
    row = cur.fetchone()
    
    if row:
        existing = row[0]
        print(f"📊 В БД уже есть {len(existing)} пользователей")
        
        # Объединяем данные (users.json имеет приоритет)
        merged = {**existing, **users}
        print(f"🔄 После объединения: {len(merged)} пользователей")
        
        cur.execute("""
            UPDATE bot_data SET value = %s WHERE key = 'users'
        """, (Json(merged),))
    else:
        # Первый импорт
        cur.execute("""
            INSERT INTO bot_data (key, value)
            VALUES ('users', %s)
        """, (Json(users),))
        print(f"✅ Импортировано {len(users)} пользователей")

    conn.commit()
    conn.close()
    print("✅ Импорт завершён!")

if __name__ == "__main__":
    import_users()
