import sqlite3
import logging
from datetime import datetime, timedelta
import asyncio
import time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters
)
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКИ ==========
TOKEN = '8331737679:AAGmlvVP0KRsy5UYPClVZ7BzBCQkaXs2NXU'  # Замените на свой токен от @BotFather
# ===============================

# Упражнения
EXERCISES = {
    'pushups': '🏋️ Отжимания',
    'squats': '🦵 Приседания', 
    'pullups': '💪 Подтягивания',
    'plank': '⏱️ Планка',
    'leg_raises': '🦵 Подъем ног'
}

# Сопоставление username с именами
USERNAME_TO_NAME = {
    'Cryptocentur': 'Бах',
    'H1ery': 'Никитос',
    'Kovalevev': 'Женя'
}

# Функция для получения отображаемого имени
def get_display_name(username, first_name, last_name):
    if username in USERNAME_TO_NAME:
        return USERNAME_TO_NAME[username]
    elif username:
        return username
    elif first_name and last_name:
        return f"{first_name} {last_name}"
    elif first_name:
        return first_name
    else:
        return "Участник"

# Главная клавиатура
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🏋️ Записать тренировку"],
        ["📊 Общая статистика", "📈 Текущий месяц"],
        ["🏆 Лидеры по упражнениям", "🎉 Общий победитель"],
        ["👤 Моя статистика", "📅 Сегодня"]
    ],
    resize_keyboard=True,
    is_persistent=True
)

# Клавиатура выбора упражнения
EXERCISE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🏋️ Отжимания", "🦵 Приседания"],
        ["💪 Подтягивания", "⏱️ Планка"],
        ["🦵 Подъем ног", "/cancel"]
    ],
    resize_keyboard=True
)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    # Создаем таблицу для тренировок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        exercise_type TEXT NOT NULL,
        count INTEGER NOT NULL,
        date DATE NOT NULL
    )
    ''')
    
    # Таблица для ежемесячных победителей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS monthly_winners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        month_year TEXT NOT NULL,
        prize_amount INTEGER DEFAULT 2000
    )
    ''')
    
    conn.commit()
    conn.close()

# Запись тренировки
def add_workout(user_id, username, first_name, last_name, exercise_type, count):
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('''
    INSERT INTO workouts (user_id, username, first_name, last_name, exercise_type, count, date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, exercise_type, count, today))
    
    conn.commit()
    conn.close()

# Получение статистики
def get_statistics(exercise_type=None, period='all'):
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    # Базовый запрос
    query = '''
    SELECT user_id, username, first_name, last_name, SUM(count) as total
    FROM workouts 
    WHERE 1=1
    '''
    
    params = []
    
    # Фильтр по упражнению
    if exercise_type:
        query += ' AND exercise_type = ?'
        params.append(exercise_type)
    
    # Фильтр по периоду
    if period == 'month':
        today = datetime.now()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        if today.month == 12:
            last_day = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
        else:
            last_day = today.replace(month=today.month+1, day=1) - timedelta(days=1)
        last_day = last_day.strftime('%Y-%m-%d')
        
        query += ' AND date BETWEEN ? AND ?'
        params.extend([first_day, last_day])
    
    # Группировка и сортировка
    query += ' GROUP BY user_id ORDER BY total DESC'
    
    cursor.execute(query, params)
    results = cursor.fetchall()
    conn.close()
    
    # Преобразуем результаты с использованием get_display_name
    formatted_results = []
    for user_id, username, first_name, last_name, total in results:
        display_name = get_display_name(username, first_name, last_name)
        formatted_results.append((user_id, display_name, total))
    
    total_all = sum([row[2] for row in formatted_results]) if formatted_results else 0
    return total_all, formatted_results

# Получение статистики по всем упражнениям
def get_all_exercises_statistics(period='all'):
    stats = {}
    for exercise in EXERCISES.keys():
        total, results = get_statistics(exercise, period)
        stats[exercise] = {
            'total': total,
            'results': results
        }
    return stats

# Получение общего рейтинга по новой системе баллов
def get_overall_ranking(period='all'):
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    # Получаем всех пользователей с тренировками за период
    if period == 'month':
        today = datetime.now()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        last_day = (today.replace(month=today.month+1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
        
        cursor.execute('''
        SELECT DISTINCT user_id, username, first_name, last_name
        FROM workouts 
        WHERE date BETWEEN ? AND ?
        ''', (first_day, last_day))
    else:
        cursor.execute('''
        SELECT DISTINCT user_id, username, first_name, last_name
        FROM workouts
        ''')
    
    all_users_data = cursor.fetchall()
    
    # Создаем словарь для хранения данных пользователей
    all_users = {}
    for user_id, username, first_name, last_name in all_users_data:
        display_name = get_display_name(username, first_name, last_name)
        all_users[user_id] = {
            'name': display_name,
            'points': 0
        }
    
    # Для каждого упражнения определяем места и начисляем баллы
    for exercise in EXERCISES.keys():
        # Получаем статистику по упражнению
        if period == 'month':
            today = datetime.now()
            first_day = today.replace(day=1).strftime('%Y-%m-%d')
            last_day = (today.replace(month=today.month+1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
            
            cursor.execute('''
            SELECT user_id, username, first_name, last_name, SUM(count) as total
            FROM workouts 
            WHERE exercise_type = ? AND date BETWEEN ? AND ?
            GROUP BY user_id
            ORDER BY total DESC
            ''', (exercise, first_day, last_day))
        else:
            cursor.execute('''
            SELECT user_id, username, first_name, last_name, SUM(count) as total
            FROM workouts 
            WHERE exercise_type = ?
            GROUP BY user_id
            ORDER BY total DESC
            ''', (exercise,))
        
        results = cursor.fetchall()
        
        # Присваиваем места и начисляем баллы
        for place, (user_id, username, first_name, last_name, total) in enumerate(results, 1):
            if user_id in all_users:
                # Новая система баллов: 10 место = 0, 9 = 10, 8 = 20, ..., 1 = 90
                # Формула: баллы = max(0, (10 - место) * 10)
                points = max(0, (10 - place) * 10)
                all_users[user_id]['points'] += points
    
    conn.close()
    
    # Сортируем по количеству баллов (убыванию)
    sorted_users = sorted(
        all_users.items(),
        key=lambda x: (-x[1]['points'], x[1]['name'])
    )
    
    return sorted_users

# Главное меню без клавиатуры (скрытая)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🏆 <b>Бот для учета тренировок</b>

Используйте команду /menu чтобы показать клавиатуру с кнопками.

<b>📋 Доступные команды:</b>
/menu - Показать клавиатуру с кнопками
/help - Справка по командам
/weekly - Еженедельный лидерборд
/cancel - Отменить текущее действие

<b>📝 Доступные упражнения:</b>
🏋️ <b>Отжимания</b> - количество раз
🦵 <b>Приседания</b> - количество раз
💪 <b>Подтягивания</b> - количество раз
⏱️ <b>Планка</b> - время в секундах
🦵 <b>Подъем ног</b> - количество раз

<b>🏆 Призы:</b>
В конце месяца победитель получает 2000 рублей!
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML
    )

# Команда для показа клавиатуры
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = """
🏆 <b>Бот для учета тренировок</b>

Выберите действие с помощью кнопок ниже:

<b>Основные функции:</b>
🏋️ <b>Записать тренировку</b> - добавить сегодняшние результаты
📊 <b>Общая статистика</b> - статистика по всем упражнениям
📈 <b>Текущий месяц</b> - статистика за этот месяц
🏆 <b>Лидеры по упражнениям</b> - топ участников по каждому упражнению
🎉 <b>Общий победитель</b> - победитель в общем зачете

<b>Личная статистика:</b>
👤 <b>Моя статистика</b> - ваши личные результаты
📅 <b>Сегодня</b> - статистика за сегодняшний день
"""
    
    await update.message.reply_text(
        menu_text,
        reply_markup=MAIN_KEYBOARD,
        parse_mode=ParseMode.HTML
    )

# Функция для отмены ожидания ввода по таймауту
async def cancel_input_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data.get('user_id')
    
    # Сбрасываем состояние ожидания ввода
    context.user_data.pop('waiting_for_count', None)
    context.user_data.pop('input_start_time', None)
    context.user_data.pop('selected_exercise', None)
    
    # Отправляем сообщение об отмене
    await context.bot.send_message(
        chat_id=job.chat_id,
        text="⏰ <b>Время на ввод истекло.</b>\n"
             "Нажмите '🏋️ Записать тренировку' чтобы попробовать снова.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD
    )

# Обработчик текстовых сообщений (кнопок)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    # Проверяем, ожидаем ли мы выбор упражнения
    if context.user_data.get('waiting_for_exercise'):
        await handle_exercise_selection(update, context)
        return
    
    # Проверяем, ожидаем ли мы ввод числа
    if context.user_data.get('waiting_for_count'):
        # Проверяем, не истекло ли время ожидания (30 секунд)
        input_start_time = context.user_data.get('input_start_time')
        if input_start_time and time.time() - input_start_time > 30:
            # Время истекло, сбрасываем состояние
            context.user_data.pop('waiting_for_count', None)
            context.user_data.pop('input_start_time', None)
            context.user_data.pop('selected_exercise', None)
            
            # Отменяем задание таймера если оно существует
            if 'timeout_job' in context.user_data:
                context.user_data['timeout_job'].schedule_removal()
                context.user_data.pop('timeout_job', None)
            
            await update.message.reply_text(
                "⏰ <b>Время на ввод истекло.</b>\n"
                "Нажмите '🏋️ Записать тренировку' чтобы попробовать снова.",
                parse_mode=ParseMode.HTML,
                reply_markup=MAIN_KEYBOARD
            )
            return
        
        # Если время не истекло, обрабатываем ввод
        await handle_workout_count(update, context)
        return
    
    # Обрабатываем нажатия кнопок только если не ожидаем ввод
    await handle_button_press(update, context)

# Обработчик выбора упражнения
async def handle_exercise_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # Определяем выбранное упражнение по тексту кнопки
    exercise_map = {
        '🏋️ Отжимания': 'pushups',
        '🦵 Приседания': 'squats',
        '💪 Подтягивания': 'pullups',
        '⏱️ Планка': 'plank',
        '🦵 Подъем ног': 'leg_raises'
    }
    
    if text in exercise_map:
        exercise = exercise_map[text]
        exercise_name = EXERCISES[exercise]
        
        # Сохраняем выбранное упражнение
        context.user_data['selected_exercise'] = exercise
        context.user_data['waiting_for_exercise'] = False
        context.user_data['waiting_for_count'] = True
        context.user_data['input_start_time'] = time.time()
        
        # Создаем задание для отмены по таймауту (30 секунд)
        job = context.job_queue.run_once(
            cancel_input_timeout,
            when=30,
            data={'user_id': update.effective_user.id},
            chat_id=update.effective_chat.id,
            name=f"input_timeout_{update.effective_user.id}"
        )
        
        # Сохраняем задание для возможной отмены
        context.user_data['timeout_job'] = job
        
        if exercise == 'plank':
            message = f"⏱️ <b>Вы выбрали: {exercise_name}</b>\n\n"
            message += "Введите время планки в <b>секундах</b>:\n"
            message += "<i>Пример: 120 (это 2 минуты)</i>\n\n"
        else:
            message = f"🏋️ <b>Вы выбрали: {exercise_name}</b>\n\n"
            message += "Введите количество повторений:\n"
            message += "<i>Пример: 50</i>\n\n"
        
        message += "<i>У вас есть 30 секунд на ввод</i>\n"
        message += "<i>Для отмены нажмите /cancel</i>"
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )
    elif text == "/cancel":
        await cancel(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите упражнение из списка:",
            reply_markup=EXERCISE_KEYBOARD
        )

# Обработчик нажатий кнопок главного меню
async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🏋️ Записать тренировку":
        # Устанавливаем состояние ожидания выбора упражнения
        context.user_data['waiting_for_exercise'] = True
        
        await update.message.reply_text(
            "🏋️ <b>Выберите упражнение:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=EXERCISE_KEYBOARD
        )
    
    elif text == "📊 Общая статистика":
        await all_time_stats(update, context)
    
    elif text == "📈 Текущий месяц":
        await month_stats(update, context)
    
    elif text == "🏆 Лидеры по упражнениям":
        await exercise_leaders(update, context)
    
    elif text == "🎉 Общий победитель":
        await overall_winner(update, context)
    
    elif text == "👤 Моя статистика":
        await my_stats(update, context)
    
    elif text == "📅 Сегодня":
        await today_stats(update, context)
    
    else:
        # Игнорируем все другие текстовые сообщения
        pass

# Обработчик ввода количества
async def handle_workout_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    # Проверяем, не отмена ли это
    if text.lower() in ['/cancel', 'отмена', 'cancel']:
        await cancel(update, context)
        return
    
    try:
        count = float(text)  # Используем float для планки (секунды могут быть дробными)
        if count <= 0:
            await update.message.reply_text(
                "❌ <b>Число должно быть больше 0.</b>\n"
                "Попробуйте еще раз (у вас 30 секунд):",
                parse_mode=ParseMode.HTML
            )
            # Сбрасываем таймер для нового ввода
            context.user_data['input_start_time'] = time.time()
            return
        
        # Проверяем максимальное значение
        exercise = context.user_data.get('selected_exercise')
        max_value = 10000 if exercise != 'plank' else 3600  # Для планки максимум 1 час
        
        if count > max_value:
            unit = "секунд" if exercise == 'plank' else "раз"
            await update.message.reply_text(
                f"😮 <b>Слишком большое число!</b>\n"
                f"Пожалуйста, введите реальное количество (у вас 30 секунд):",
                parse_mode=ParseMode.HTML
            )
            # Сбрасываем таймер для нового ввода
            context.user_data['input_start_time'] = time.time()
            return
        
        # Записываем в базу
        add_workout(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            exercise,
            int(count) if exercise != 'plank' else count
        )
        
        # Сбрасываем состояние и отменяем таймер
        context.user_data.pop('waiting_for_count', None)
        context.user_data.pop('input_start_time', None)
        context.user_data.pop('selected_exercise', None)
        if 'timeout_job' in context.user_data:
            context.user_data['timeout_job'].schedule_removal()
            context.user_data.pop('timeout_job', None)
        
        exercise_name = EXERCISES[exercise]
        unit = "секунд" if exercise == 'plank' else "раз"
        
        await update.message.reply_text(
            f"✅ <b>Отлично! Записал {exercise_name}:</b>\n"
            f"<b>{count} {unit}</b>\n\n"
            f"<i>Продолжайте в том же духе! 💪</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_KEYBOARD
        )
        
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Пожалуйста, введите число.</b>\n"
            "Пример: 50 (для планки можно использовать десятичные числа: 120.5)\n\n"
            "<i>У вас 30 секунд на ввод</i>\n"
            "<i>Для отмены нажмите /cancel</i>",
            parse_mode=ParseMode.HTML
        )
        # Сбрасываем таймер для нового ввода
        context.user_data['input_start_time'] = time.time()

# Команда отмены
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбрасываем все состояния
    context.user_data.pop('waiting_for_exercise', None)
    context.user_data.pop('waiting_for_count', None)
    context.user_data.pop('input_start_time', None)
    context.user_data.pop('selected_exercise', None)
    
    # Отменяем задание таймера если оно существует
    if 'timeout_job' in context.user_data:
        context.user_data['timeout_job'].schedule_removal()
        context.user_data.pop('timeout_job', None)
    
    await update.message.reply_text(
        "✅ Операция отменена.",
        reply_markup=MAIN_KEYBOARD
    )

# Личная статистика пользователя
async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    # Общая статистика по всем упражнениям
    cursor.execute('''
    SELECT exercise_type, 
           SUM(count) as total,
           COUNT(DISTINCT date) as days,
           AVG(count) as average,
           MAX(count) as max_count
    FROM workouts 
    WHERE user_id = ?
    GROUP BY exercise_type
    ORDER BY exercise_type
    ''', (user.id,))
    
    exercise_stats = cursor.fetchall()
    
    # Статистика за месяц
    today = datetime.now()
    first_day = today.replace(day=1).strftime('%Y-%m-%d')
    last_day = (today.replace(month=today.month+1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    cursor.execute('''
    SELECT exercise_type, SUM(count) as month_total
    FROM workouts 
    WHERE user_id = ? AND date BETWEEN ? AND ?
    GROUP BY exercise_type
    ''', (user.id, first_day, last_day))
    
    month_stats = dict(cursor.fetchall())
    
    # Статистика за сегодня
    today_str = today.strftime('%Y-%m-%d')
    cursor.execute('''
    SELECT exercise_type, SUM(count) as today_total
    FROM workouts 
    WHERE user_id = ? AND date = ?
    GROUP BY exercise_type
    ''', (user.id, today_str))
    
    today_stats = dict(cursor.fetchall())
    
    conn.close()
    
    user_name = get_display_name(user.username, user.first_name, user.last_name)
    
    message = f"👤 <b>Личная статистика {user_name}</b>\n\n"
    
    # Статистика за сегодня
    if today_stats:
        message += "<b>Сегодня:</b>\n"
        for exercise, total in today_stats.items():
            exercise_name = EXERCISES.get(exercise, exercise)
            unit = "секунд" if exercise == 'plank' else "раз"
            display_total = int(total) if exercise != 'plank' else total
            message += f"  {exercise_name}: {display_total} {unit}\n"
        message += "\n"
    
    # Статистика за месяц
    if month_stats:
        message += "<b>В этом месяце:</b>\n"
        for exercise, total in month_stats.items():
            exercise_name = EXERCISES.get(exercise, exercise)
            unit = "секунд" if exercise == 'plank' else "раз"
            display_total = int(total) if exercise != 'plank' else total
            message += f"  {exercise_name}: {display_total} {unit}\n"
        message += "\n"
    
    # Общая статистика по упражнениям
    if exercise_stats:
        message += "<b>Общая статистика:</b>\n"
        for exercise_type, total, days, average, max_count in exercise_stats:
            exercise_name = EXERCISES.get(exercise_type, exercise_type)
            unit = "секунд" if exercise_type == 'plank' else "раз"
            message += f"\n<b>{exercise_name}:</b>\n"
            display_total = int(total) if exercise_type != 'plank' else total
            message += f"  Всего: {display_total} {unit}\n"
            message += f"  Дней тренировок: {days}\n"
            if days > 0:
                display_avg = int(average) if exercise_type != 'plank' else round(average, 1)
                display_max = int(max_count) if exercise_type != 'plank' else max_count
                message += f"  Среднее: {display_avg} {unit}\n"
                message += f"  Максимум: {display_max} {unit}\n"
    
    if not exercise_stats:
        message += "У вас пока нет записанных тренировок.\n"
        message += "Начните свою первую тренировку! 🏃‍♂️"
    else:
        message += "\n<b>Продолжайте в том же духе! 💪</b>"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Статистика за сегодня
async def today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('workouts.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Получаем статистику по упражнениям за сегодня
    cursor.execute('''
    SELECT exercise_type, username, first_name, last_name, SUM(count) as total
    FROM workouts 
    WHERE date = ?
    GROUP BY exercise_type, user_id
    ORDER BY exercise_type, total DESC
    ''', (today,))
    
    results = cursor.fetchall()
    conn.close()
    
    # Группируем по упражнениям
    grouped = {}
    for exercise_type, username, first_name, last_name, total in results:
        if exercise_type not in grouped:
            grouped[exercise_type] = []
        display_name = get_display_name(username, first_name, last_name)
        grouped[exercise_type].append((display_name, total))
    
    message = f"📅 <b>Статистика за сегодня ({today})</b>\n\n"
    
    if grouped:
        for exercise_type, users in grouped.items():
            exercise_name = EXERCISES.get(exercise_type, exercise_type)
            unit = "секунд" if exercise_type == 'plank' else "раз"
            
            message += f"<b>{exercise_name}:</b>\n"
            total_exercise = sum(total for _, total in users)
            display_total = int(total_exercise) if exercise_type != 'plank' else total_exercise
            message += f"<i>Всего: {display_total} {unit}</i>\n\n"
            
            for i, (name, user_total) in enumerate(users[:10], 1):
                display_user_total = int(user_total) if exercise_type != 'plank' else user_total
                message += f"{i}. {name} - {display_user_total} {unit}\n"
            
            if len(users) > 10:
                message += f"...и ещё {len(users) - 10} участников\n"
            
            message += "\n"
    else:
        message += "Сегодня еще никто не тренировался 😴\n\n"
        message += "Будьте первым! 💪"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Статистика за все время
async def all_time_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_all_exercises_statistics('all')
    
    message = "📊 <b>Общая статистика за всё время</b>\n\n"
    
    for exercise_type, data in stats.items():
        exercise_name = EXERCISES.get(exercise_type, exercise_type)
        unit = "секунд" if exercise_type == 'plank' else "раз"
        
        message += f"<b>{exercise_name}:</b>\n"
        display_total = int(data['total']) if exercise_type != 'plank' else data['total']
        message += f"<i>Всего: {display_total} {unit}</i>\n\n"
        
        if data['results']:
            for i, (user_id, name, total) in enumerate(data['results'][:10], 1):
                display_user_total = int(total) if exercise_type != 'plank' else total
                message += f"{i}. {name} - {display_user_total} {unit}\n"
            
            if len(data['results']) > 10:
                message += f"...и ещё {len(data['results']) - 10} участников\n"
        else:
            message += "Нет данных\n"
        
        message += "\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Статистика за текущий месяц
async def month_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_all_exercises_statistics('month')
    today = datetime.now()
    month_name = today.strftime('%B %Y')
    
    message = f"📈 <b>Статистика за {month_name}</b>\n\n"
    
    for exercise_type, data in stats.items():
        exercise_name = EXERCISES.get(exercise_type, exercise_type)
        unit = "секунд" if exercise_type == 'plank' else "раз"
        
        message += f"<b>{exercise_name}:</b>\n"
        display_total = int(data['total']) if exercise_type != 'plank' else data['total']
        message += f"<i>Всего: {display_total} {unit}</i>\n\n"
        
        if data['results']:
            for i, (user_id, name, total) in enumerate(data['results'][:10], 1):
                display_user_total = int(total) if exercise_type != 'plank' else total
                message += f"{i}. {name} - {display_user_total} {unit}\n"
            
            if len(data['results']) > 10:
                message += f"...и ещё {len(data['results']) - 10} участников\n"
        else:
            message += "Нет данных\n"
        
        message += "\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Лидеры по упражнениям
async def exercise_leaders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_all_exercises_statistics('month')
    today = datetime.now()
    month_name = today.strftime('%B %Y')
    
    message = f"🏆 <b>Лидеры по упражнениям ({month_name})</b>\n\n"
    
    for exercise_type, data in stats.items():
        exercise_name = EXERCISES.get(exercise_type, exercise_type)
        unit = "секунд" if exercise_type == 'plank' else "раз"
        
        if data['results']:
            message += f"<b>{exercise_name}:</b>\n"
            
            # Показываем топ-3 с медалями
            top_users = data['results'][:3]
            
            for i, (user_id, name, total) in enumerate(top_users, 1):
                display_user_total = int(total) if exercise_type != 'plank' else total
                if i == 1:
                    message += f"🥇 {name} - {display_user_total} {unit}\n"
                elif i == 2:
                    message += f"🥈 {name} - {display_user_total} {unit}\n"
                elif i == 3:
                    message += f"🥉 {name} - {display_user_total} {unit}\n"
            
            message += "\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Общий победитель по новой системе
async def overall_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = get_overall_ranking('month')
    today = datetime.now()
    month_name = today.strftime('%B %Y')
    
    message = f"🎉 <b>Общий зачет ({month_name})</b>\n\n"
    message += "<i>Система подсчета очков:</i>\n"
    message += "<i>• За каждое упражнение начисляются очки по местам</i>\n"
    message += "<i>• 1 место = 90 очков, 2 = 80, 3 = 70, 4 = 60, 5 = 50,</i>\n"
    message += "<i>  6 = 40, 7 = 30, 8 = 20, 9 = 10, 10 и ниже = 0</i>\n"
    message += "<i>• Очки суммируются по всем 5 упражнениям</i>\n\n"
    
    if ranking:
        # Показываем всех участников
        for i, (user_id, data) in enumerate(ranking, 1):
            name = data['name']
            points = data['points']
            
            if i == 1:
                message += f"🥇 <b>{name}</b> - {points} очков\n"
            elif i == 2:
                message += f"🥈 <b>{name}</b> - {points} очков\n"
            elif i == 3:
                message += f"🥉 <b>{name}</b> - {points} очков\n"
            else:
                message += f"{i}. <b>{name}</b> - {points} очков\n"
        
        # Определяем победителя
        if ranking[0][1]['points'] > 0:
            winner_name = ranking[0][1]['name']
            winner_points = ranking[0][1]['points']
            message += f"\n<b>🏆 ПОБЕДИТЕЛЬ: {winner_name} с {winner_points} очками!</b>\n"
            message += f"<b>Приз: 2000 рублей! 💰</b>"
        else:
            message += "\n<b>Еще нет данных для определения победителя.</b>"
    else:
        message += "Пока нет участников с тренировками в этом месяце.\n"
        message += "Начните тренировки! 💪"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Команда для еженедельного лидерборда
async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = get_overall_ranking('month')
    today = datetime.now()
    month_name = today.strftime('%B %Y')
    
    message = f"🏆 <b>Еженедельный лидерборд ({month_name})</b>\n\n"
    
    if ranking:
        # Показываем топ-10
        for i, (user_id, data) in enumerate(ranking[:10], 1):
            name = data['name']
            points = data['points']
            
            if i == 1:
                message += f"🥇 <b>{name}</b> - {points} очков\n"
            elif i == 2:
                message += f"🥈 <b>{name}</b> - {points} очков\n"
            elif i == 3:
                message += f"🥉 <b>{name}</b> - {points} очков\n"
            else:
                message += f"{i}. <b>{name}</b> - {points} очков\n"
    else:
        message += "Пока нет данных для лидерборда.\n"
    
    message += "\n<i>Не сдавайтесь! Каждая тренировка приближает вас к победе! 💪</i>"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Команда помощи
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>📋 Доступные команды:</b>

/start - Начальная информация
/menu - Показать клавиатуру с кнопками
/help - Эта справка
/weekly - Еженедельный лидерборд
/cancel - Отменить текущее действие

<b>🎯 Как пользоваться:</b>
1. Нажмите /menu чтобы показать клавиатуру
2. Нажмите "Записать тренировку"
3. Выберите упражнение
4. Введите количество в течение 30 секунд
5. Смотрите статистику через кнопки

<b>📝 Упражнения:</b>
🏋️ <b>Отжимания</b> - количество раз
🦵 <b>Приседания</b> - количество раз  
💪 <b>Подтягивания</b> - количество раз
⏱️ <b>Планка</b> - время в секундах
🦵 <b>Подъем ног</b> - количество раз

<b>🏆 Система очков для общего зачета:</b>
• За каждое упражнение: 1 место = 90 очков, 2 = 80, 3 = 70,
  4 = 60, 5 = 50, 6 = 40, 7 = 30, 8 = 20, 9 = 10, 10 и ниже = 0
• Очки суммируются по всем упражнениям

<b>💰 Призы:</b>
В конце месяца победитель в общем зачете получает 2000 рублей!
"""
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML
    )

# Главная функция
def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("weekly", weekly))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # Обработчик всех текстовых сообщений
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )
    
    # Запуск бота
    print("=" * 50)
    print("🤖 Бот для учета тренировок запущен!")
    print("📱 Работает на Android через Pydroid 3")
    print("=" * 50)
    print("\n🎯 Особенности этой версии:")
    print("✅ 5 упражнений: отжимания, приседания, подтягивания, планка, подъем ног")
    print("✅ Клавиатура скрыта по умолчанию (показывается по команде /menu)")
    print("✅ Новая система подсчета очков: 90-80-70-60-50-40-30-20-10-0")
    print("✅ Имена участников: Бах, Никитос, Женя (по username)")
    print("✅ Общий зачет по сумме очков из всех упражнений")
    print("=" * 50)
    print("\n💡 Настройка бота через @BotFather:")
    print("1. Добавьте команды в меню бота:")
    print("   start - Начальная информация")
    print("   menu - Показать клавиатуру")
    print("   help - Помощь")
    print("   weekly - Лидерборд")
    print("2. Добавьте бота в группу")
    print("3. Назначьте администратором")
    print("4. Напишите в группе /menu")
    print("=" * 50)
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        print("Проверьте интернет соединение и токен бота")

if __name__ == '__main__':
    main()
