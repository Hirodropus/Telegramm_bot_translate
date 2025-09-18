
import telebot
import requests
import random
import psycopg2
from psycopg2 import sql
from telebot import types, TeleBot, custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
import logging


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация базы данных (для удаленного сервера)
DB_CONFIG = {
    'dbname': 'english_bot_db',
    'user': 'postgres', # замените на вашего пользователя
    'password': 'xxxxxx', # замените на ваш пароль
    'host': 'xxx.xxx.xxx.xxx',
    'port': '5432'
}

# Токены
TOKEN = '' # вствьте токен вашего теkеграмм бота


# Инициализация бота
state_storage = StateMemoryStorage()
bot = TeleBot(TOKEN, state_storage=state_storage)

# Глобальные переменные
known_users = []
userStep = {}
buttons = []

class Command:
    ADD_WORD = 'Добавить слово ➕'
    DELETE_WORD = 'Удалить слово🔙'
    NEXT = 'Дальше ⏭'
    STATS = 'Статистика 📊'
    RESTART = 'Перезапустить 🔄'

class MyStates(StatesGroup):
    target_word = State()
    translate_word = State()
    another_words = State()
    add_english = State()
    add_russian = State()

# Функции для работы с базой данных с обработкой ошибок
def get_db_connection():
    """Создание соединения с удаленной БД с обработкой ошибок"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None

def get_or_create_user(telegram_id, username, first_name, last_name):
    """Получение или создание пользователя"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
                RETURNING id
            """, (telegram_id, username or '', first_name or '', last_name or ''))
            user_id = cur.fetchone()[0]
            conn.commit()
            return user_id
    except Exception as e:
        logger.error(f"Ошибка при создании пользователя: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_random_word(user_id):
    """Получение случайного слова для изучения"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            # Получаем случайное слово
            cur.execute("""
                SELECT w.id, w.english_word, w.russian_translation
                FROM words w
                WHERE w.id NOT IN (
                    SELECT uw.word_id FROM user_words uw 
                    WHERE uw.user_id = %s AND uw.correct_answers >= 3
                )
                ORDER BY RANDOM()
                LIMIT 1
            """, (user_id,))
            result = cur.fetchone()

            if not result:
                # Если все слова изучены, берем любое случайное слово
                cur.execute("""
                    SELECT id, english_word, russian_translation
                    FROM words
                    ORDER BY RANDOM()
                    LIMIT 1
                """)
                result = cur.fetchone()

            if result:
                return {
                    'id': result[0],
                    'english_word': result[1],
                    'russian_translation': result[2]
                }
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении слова: {e}")
        return None
    finally:
        conn.close()

def get_random_words(exclude_word_id, limit=3):
    """Получение случайных слов для вариантов ответа"""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT english_word
                FROM words
                WHERE id != %s
                ORDER BY RANDOM()
                LIMIT %s
            """, (exclude_word_id, limit))
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении слов: {e}")
        return []
    finally:
        conn.close()


def update_user_stats(user_id, is_correct):
    """Обновление статистики пользователя"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            if is_correct:
                cur.execute("""
                    INSERT INTO user_stats (user_id, total_correct, last_activity)
                    VALUES (%s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                    total_correct = user_stats.total_correct + 1,
                    last_activity = CURRENT_TIMESTAMP
                """, (user_id,))
            else:
                cur.execute("""
                    INSERT INTO user_stats (user_id, total_wrong, last_activity)
                    VALUES (%s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                    total_wrong = user_stats.total_wrong + 1,
                    last_activity = CURRENT_TIMESTAMP
                """, (user_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении статистики: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def update_user_word(user_id, word_id, is_correct):
    """Обновление прогресса изучения слова"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            if is_correct:
                cur.execute("""
                    INSERT INTO user_words (user_id, word_id, correct_answers, last_practiced)
                    VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, word_id) DO UPDATE SET
                    correct_answers = user_words.correct_answers + 1,
                    last_practiced = CURRENT_TIMESTAMP
                """, (user_id, word_id))
            else:
                cur.execute("""
                    INSERT INTO user_words (user_id, word_id, wrong_answers, last_practiced)
                    VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, word_id) DO UPDATE SET
                    wrong_answers = user_words.wrong_answers + 1,
                    last_practiced = CURRENT_TIMESTAMP
                """, (user_id, word_id))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении слова: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def add_new_word(english_word, russian_translation):
    """Добавление нового слова в базу"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO words (english_word, russian_translation)
                VALUES (%s, %s)
                ON CONFLICT (english_word) DO NOTHING
                RETURNING id
            """, (english_word.lower(), russian_translation.lower()))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка при добавлении слова: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_user_word(user_id, word_text):
    """Удаление слова из изучения пользователем"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM user_words uw
                USING words w
                WHERE uw.word_id = w.id 
                AND uw.user_id = %s 
                AND w.english_word = %s
            """, (user_id, word_text.lower()))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка при удалении слова: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_user_stats(user_id):
    """Получение статистики пользователя"""
    conn = get_db_connection()
    if not conn:
        return {'correct': 0, 'wrong': 0, 'learned': 0}

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT total_correct, total_wrong, words_learned
                FROM user_stats
                WHERE user_id = %s
            """, (user_id,))
            result = cur.fetchone()
            if result:
                return {
                    'correct': result[0] or 0,
                    'wrong': result[1] or 0,
                    'learned': result[2] or 0
                }
            return {'correct': 0, 'wrong': 0, 'learned': 0}
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return {'correct': 0, 'wrong': 0, 'learned': 0}
    finally:
        conn.close()

def check_db_connection():
    """Проверка соединения с БД"""
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
            return True
        return False
    except:
        return False


@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 English Learning Bot - Помощь

Доступные команды:
/start - Начать изучение слов
/cards - Показать карточки для изучения
/help - Показать эту справку

Кнопки:
Дальше ⏭ - Следующее слово
Добавить слово ➕ - Добавить новое слово
Удалить слово🔙 - Удалить слово из изучения
Статистика 📊 - Показать статистику
Перезапустить 🔄 - Начать заново

Как пользоваться:
1. Нажмите /start чтобы начать
2. Выбирайте правильный перевод русского слова
3. Используйте кнопки для навигации
4. Добавляйте свои слова через "Добавить слово ➕"
"""
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['start', 'cards'])
def create_cards(message):
    if not check_db_connection():
        bot.send_message(message.chat.id, "⚠️ Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cid = message.chat.id
    user_id = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )

    if not user_id:
        bot.send_message(message.chat.id, "⚠️ Ошибка при создании пользователя.")
        return

    if cid not in known_users:
        known_users.append(cid)
        userStep[cid] = 0

    show_next_card(message, user_id)


def show_next_card(message, user_id):
    word_data = get_random_word(user_id)
    if not word_data:
        bot.send_message(message.chat.id,
                         "📚 В базе данных нет слов для изучения! Используйте /add_word чтобы добавить слова.")
        return

    other_words = get_random_words(word_data['id'], 3)
    other_words.append(word_data['english_word'])
    random.shuffle(other_words)

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    global buttons
    buttons = []

    for word in other_words:
        btn = types.KeyboardButton(word)
        buttons.append(btn)

    next_btn = types.KeyboardButton(Command.NEXT)
    add_word_btn = types.KeyboardButton(Command.ADD_WORD)
    delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
    stats_btn = types.KeyboardButton(Command.STATS)
    restart_btn = types.KeyboardButton(Command.RESTART)

    buttons.extend([next_btn, add_word_btn, delete_word_btn, stats_btn, restart_btn])
    markup.add(*buttons)

    greeting = f"Выбери перевод слова:\n🇷🇺 {word_data['russian_translation']}"
    bot.send_message(message.chat.id, greeting, reply_markup=markup)

    bot.set_state(message.from_user.id, MyStates.target_word, message.chat.id)
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['target_word'] = word_data['english_word']
        data['translate_word'] = word_data['russian_translation']
        data['word_id'] = word_data['id']
        data['other_words'] = other_words


@bot.message_handler(func=lambda message: message.text == Command.NEXT)
def next_cards(message):
    user_id = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    if user_id:
        show_next_card(message, user_id)


@bot.message_handler(func=lambda message: message.text == Command.RESTART)
def restart_bot(message):
    create_cards(message)


@bot.message_handler(func=lambda message: message.text == Command.DELETE_WORD)
def delete_word(message):
    user_id = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )

    if not user_id:
        bot.send_message(message.chat.id, "⚠️ Ошибка доступа к базе данных.")
        return

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        if delete_user_word(user_id, data['target_word']):
            bot.send_message(message.chat.id, f"🗑️ Слово '{data['target_word']}' удалено списка изучения!")
        else:
            bot.send_message(message.chat.id, "ℹ️ Слово не найдено в списке изучения!")


@bot.message_handler(func=lambda message: message.text == Command.ADD_WORD)
def add_word(message):
    msg = bot.send_message(message.chat.id, "✏️ Введите английское слово:")
    bot.register_next_step_handler(msg, process_english_word)


def process_english_word(message):
    if message.text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Отменено. Используйте команды из меню.")
        return

    bot.set_state(message.from_user.id, MyStates.add_english, message.chat.id)
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['new_english_word'] = message.text.strip()

    msg = bot.send_message(message.chat.id, "🌐 Теперь введите русский перевод:")
    bot.register_next_step_handler(msg, process_russian_translation)


def process_russian_translation(message):
    if message.text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Отменено. Используйте команды из меню.")
        return

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        english_word = data['new_english_word']
        russian_translation = message.text.strip()

        if add_new_word(english_word, russian_translation):
            bot.send_message(message.chat.id, f"✅ Слово '{english_word}' добавлено в базу данных!")
        else:
            bot.send_message(message.chat.id, "❌ Не удалось добавить слово. Возможно, оно уже существует.")


@bot.message_handler(func=lambda message: message.text == Command.STATS)
def show_stats(message):
    user_id = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )

    if not user_id:
        bot.send_message(message.chat.id, "⚠️ Ошибка доступа к статистике.")
        return

    stats = get_user_stats(user_id)
    total = stats['correct'] + stats['wrong']
    accuracy = (stats['correct'] / total * 100) if total > 0 else 0

    stats_text = f"""
📊 Ваша статистика:

✅ Правильных ответов: {stats['correct']}
❌ Неправильных ответов: {stats['wrong']}
🎯 Точность: {accuracy:.1f}%
📚 Изучено слов: {stats['learned']}
"""
    bot.send_message(message.chat.id, stats_text)


@bot.message_handler(func=lambda message: True, content_types=['text'])
def message_reply(message):
    if message.text.startswith('/'):
        return

    user_id = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )

    if not user_id:
        bot.send_message(message.chat.id, "⚠️ Ошибка доступа к базе данных.")
        return

    text = message.text
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        if 'target_word' not in data:
            create_cards(message)
            return

        target_word = data['target_word']
        word_id = data['word_id']

        if text == target_word:
            # Правильный ответ
            update_user_stats(user_id, True)
            update_user_word(user_id, word_id, True)

            hint_text = f"✅ Отлично!\n{target_word} -> {data['translate_word']}"
            # Помечаем правильный ответ
            updated_buttons = []
            for btn_text in data['other_words']:
                if btn_text == text:
                    updated_buttons.append(types.KeyboardButton(btn_text + ' ✅'))
                else:
                    updated_buttons.append(types.KeyboardButton(btn_text))
        else:
            # Неправильный ответ
            update_user_stats(user_id, False)
            update_user_word(user_id, word_id, False)

            hint_text = f"❌ Допущена ошибка!\nПравильный ответ: {target_word} -> {data['translate_word']}"
            # Помечаем неправильный ответ
            updated_buttons = []
            for btn_text in data['other_words']:
                if btn_text == text:
                    updated_buttons.append(types.KeyboardButton(btn_text + ' ❌'))
                elif btn_text == target_word:
                    updated_buttons.append(types.KeyboardButton(btn_text + ' ✅'))
                else:
                    updated_buttons.append(types.KeyboardButton(btn_text))

    # Добавляем кнопки управления
    next_btn = types.KeyboardButton(Command.NEXT)
    add_word_btn = types.KeyboardButton(Command.ADD_WORD)
    delete_word_btn = types.KeyboardButton(Command.DELETE_WORD)
    stats_btn = types.KeyboardButton(Command.STATS)
    restart_btn = types.KeyboardButton(Command.RESTART)

    updated_buttons.extend([next_btn, add_word_btn, delete_word_btn, stats_btn, restart_btn])
    markup.add(*updated_buttons)

    bot.send_message(message.chat.id, hint_text, reply_markup=markup)



@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 English Learning Bot - Помощь

Доступные команды:
/start - Начать изучение слов
/cards - Показать карточки для изучения
/help - Показать эту справку

Кнопки:
Дальше ⏭ - Следующее слово
Добавить слово ➕ - Добавить новое слово
Удалить слово🔙 - Удалить слово из изучения
Статистика 📊 - Показать статистику
Перезапустить 🔄 - Начать заново
"""
    bot.reply_to(message, help_text)


@bot.message_handler(commands=['db_status'])
def db_status(message):
    """Проверка статуса подключения к БД"""
    if check_db_connection():
        bot.reply_to(message, "✅ Подключение к базе данных активно")
    else:
        bot.reply_to(message, "❌ Нет подключения к базе данных")


# Добавляем кастомные фильтры
bot.add_custom_filter(custom_filters.StateFilter(bot))

if __name__ == '__main__':
    logger.info('Запуск бота...')
    print('Бот запущен...')
    print('Для завершения нажмите Ctrl+C')

    # Проверка подключения к БД при запуске
    if check_db_connection():
        print('✅ Подключение к базе данных установлено')
    else:
        print('❌ Ошибка подключения к базе данных')

    try:
        bot.infinity_polling(timeout=60, skip_pending=True)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")