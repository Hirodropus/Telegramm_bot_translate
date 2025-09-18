import psycopg2
import sys

def setup_database():

    # Конфигурация подключения (замените на свои данные)
    DB_CONFIG = {
        'dbname': 'postgres',
        'user': 'postgres',  # замените на вашего пользователя
        'password': 'xxxxxxx',  # замените на ваш пароль
        'host': 'xxx.xxx.xxx.xxx',
        'port': '5432'
    }


    # Начальные слова для добавления
    INITIAL_WORDS = [
        ('hello', 'привет'), ('world', 'мир'), ('peace', 'покой'),
        ('love', 'любовь'), ('house', 'дом'), ('car', 'машина'),
        ('book', 'книга'), ('water', 'вода'), ('sun', 'солнце'),
        ('moon', 'луна'), ('star', 'звезда'), ('tree', 'дерево'),
        ('computer', 'компьютер'), ('phone', 'телефон'), ('friend', 'друг')
    ]

    conn = None
    cur = None

    try:
        print("=== Создание базы данных для Telegram-бота изучения английского ===\n")

        # Подключаемся к PostgreSQL
        print("🔗 Подключение к PostgreSQL...")
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True  # Для создания базы данных
        cur = conn.cursor()

        # Проверяем существование базы данных
        print("🔍 Проверка существования базы данных...")
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'english_bot_db'")
        db_exists = cur.fetchone()

        if db_exists:
            print("⚠️ База данных 'english_bot_db' уже существует.")
        else:
            # Создаем базу данных
            print("📁 Создание базы данных 'english_bot_db'...")
            cur.execute("CREATE DATABASE english_bot_db")
            print("✅ База данных создана успешно!")

        # Закрываем текущее соединение
        cur.close()
        conn.close()

        # Подключаемся к новой базе данных
        print("🔗 Подключение к созданной базе данных...")
        DB_CONFIG['dbname'] = 'english_bot_db'
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Создаем таблицы
        print("📊 Создание таблиц...")

        # Таблица пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(100),
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ Таблица 'users' создана/проверена")

        # Таблица слов
        cur.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY,
                english_word VARCHAR(100) UNIQUE NOT NULL,
                russian_translation VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ Таблица 'words' создана/проверена")

        # Таблица изучения слов
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_words (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                word_id INTEGER REFERENCES words(id) ON DELETE CASCADE,
                correct_answers INTEGER DEFAULT 0,
                wrong_answers INTEGER DEFAULT 0,
                last_practiced TIMESTAMP,
                UNIQUE(user_id, word_id)
            )
        """)
        print("✅ Таблица 'user_words' создана/проверена")

        # Таблица статистики
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE UNIQUE,
                total_correct INTEGER DEFAULT 0,
                total_wrong INTEGER DEFAULT 0,
                words_learned INTEGER DEFAULT 0,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ Таблица 'user_stats' создана/проверена")

        # Фиксируем создание таблиц
        conn.commit()
        print("✅ Все таблицы успешно созданы!")

        # Добавляем начальные слова с индивидуальными транзакциями
        print("\n📝 Добавление начальных слов...")
        added_count = 0
        skipped_count = 0

        for english, russian in INITIAL_WORDS:
            try:
                # Пытаемся добавить слово
                cur.execute(
                    "INSERT INTO words (english_word, russian_translation) VALUES (%s, %s)",
                    (english.lower(), russian.lower())
                )
                conn.commit()  # Фиксируем каждое успешное добавление
                added_count += 1
                print(f"   ✅ Добавлено: {english} -> {russian}")

            except psycopg2.IntegrityError:
                # Дубликат - откатываем и продолжаем
                conn.rollback()
                skipped_count += 1
                print(f"   ⚠️ Пропущено (дубликат): {english} -> {russian}")

            except Exception as e:
                conn.rollback()
                print(f"   ❌ Ошибка при добавлении: {english} -> {russian} - {e}")

        # Создаем индексы для улучшения производительности
        print("\n⚡ Создание индексов...")
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)",
            "CREATE INDEX IF NOT EXISTS idx_words_english ON words(english_word)",
            "CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_words_word_id ON user_words(word_id)"
        ]

        for index_sql in indexes:
            try:
                cur.execute(index_sql)
                print(f"✅ Индекс создан")
            except Exception as e:
                print(f"⚠️ Ошибка создания индекса: {e}")

        conn.commit()

        # Проверяем результат
        print("\n🔍 Проверка результата...")

        # Проверяем количество слов
        cur.execute("SELECT COUNT(*) FROM words")
        total_words = cur.fetchone()[0]
        print(f"   Всего слов в базе: {total_words}")

        # Показываем все добавленные слова
        cur.execute("SELECT english_word, russian_translation FROM words ORDER BY id")
        all_words = cur.fetchall()
        print(f"   Список добавленных слов:")
        for i, word in enumerate(all_words, 1):
            print(f"     {i}. {word[0]} -> {word[1]}")

        # Выводим итоговую статистику
        print(f"\n📊 ИТОГОВАЯ СТАТИСТИКА:")
        print(f"   ✅ Успешно добавлено слов: {added_count}")
        print(f"   ⚠️ Пропущено дубликатов: {skipped_count}")
        print(f"   📚 Всего слов в базе: {total_words}")

        if added_count > 0:
            print("\n🎉 База данных создана успешно!")
        else:
            print("\n⚠️ Слова не были добавлены. Возможно, они уже существуют в базе.")

    except psycopg2.OperationalError as e:
        print(f"\n❌ Ошибка подключения к PostgreSQL: {e}")
        print("   Убедитесь, что:")
        print("   1. PostgreSQL запущен")
        print("   2. Правильно указаны учетные данные")
        print("   3. Хост и порт корректны")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        sys.exit(1)

    finally:
        # Всегда закрываем соединение
        if cur:
            cur.close()
        if conn:
            conn.close()
        print("\n🔚 Соединение с базой данных закрыто.")


if __name__ == "__main__":
    setup_database()