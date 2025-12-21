import sqlite3
import logging
from datetime import datetime, timedelta
import asyncio
import time
from telegram import Update, ReplyKeyboardMarkup
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

# Создаем постоянную клавиатуру
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🏋️ Записать тренировку"],
        ["📊 Статистика", "📈 Текущий месяц"],
        ["🏆 Лидеры месяца", "🎉 Победитель"],
        ["👤 Моя статистика", "📅 Сегодня"]
    ],
    resize_keyboard=True,
    is_persistent=True
)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('pushups.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pushups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        count INTEGER NOT NULL,
        date DATE NOT NULL
    )
    ''')
    
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

# Запись отжиманий
def add_pushups(user_id, username, first_name, last_name, count):
    conn = sqlite3.connect('pushups.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('''
    INSERT INTO pushups (user_id, username, first_name, last_name, count, date)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, count, today))
    
    conn.commit()
    conn.close()

# Получение статистики
def get_statistics(period='all'):
    conn = sqlite3.connect('pushups.db')
    cursor = conn.cursor()
    
    if period == 'month':
        today = datetime.now()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        if today.month == 12:
            last_day = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
        else:
            last_day = today.replace(month=today.month+1, day=1) - timedelta(days=1)
        last_day = last_day.strftime('%Y-%m-%d')
        
        cursor.execute('''
        SELECT user_id, 
               COALESCE(username, first_name || ' ' || COALESCE(last_name, '')),
               SUM(count) as total
        FROM pushups 
        WHERE date BETWEEN ? AND ?
        GROUP BY user_id
        ORDER BY total DESC
        ''', (first_day, last_day))
    else:
        cursor.execute('''
        SELECT user_id, 
               COALESCE(username, first_name || ' ' || COALESCE(last_name, '')),
               SUM(count) as total
        FROM pushups 
        GROUP BY user_id
        ORDER BY total DESC
        ''')
    
    results = cursor.fetchall()
    conn.close()
    
    total_all = sum([row[2] for row in results]) if results else 0
    return total_all, results

# Главное меню с клавиатурой
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🏆 <b>Бот для учета отжиманий</b>

Выберите действие с помощью кнопок ниже:

<b>Основные функции:</b>
🏋️ <b>Записать тренировку</b> - добавить сегодняшние отжимания
📊 <b>Статистика</b> - общая статистика за всё время
📈 <b>Текущий месяц</b> - статистика за этот месяц
🏆 <b>Лидеры месяца</b> - топ участников текущего месяца
🎉 <b>Победитель</b> - победитель текущего месяца

<b>Личная статистика:</b>
👤 <b>Моя статистика</b> - ваши личные результаты
📅 <b>Сегодня</b> - статистика за сегодняшний день

<b>🏆 Призы:</b>
В конце месяца победитель получает 2000 рублей!
"""
    
    await update.message.reply_text(
        welcome_text,
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
    
    # Проверяем, ожидаем ли мы ввод числа отжиманий
    if context.user_data.get('waiting_for_count'):
        # Проверяем, не истекло ли время ожидания (5 секунд)
        input_start_time = context.user_data.get('input_start_time')
        if input_start_time and time.time() - input_start_time > 5:
            # Время истекло, сбрасываем состояние
            context.user_data.pop('waiting_for_count', None)
            context.user_data.pop('input_start_time', None)
            
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
        await handle_pushup_count(update, context)
        return
    
    # Обрабатываем нажатия кнопок только если не ожидаем ввод
    await handle_button_press(update, context)

# Обработчик нажатий кнопок
async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🏋️ Записать тренировку":
        # Устанавливаем состояние ожидания ввода
        context.user_data['waiting_for_count'] = True
        context.user_data['input_start_time'] = time.time()
        
        # Создаем задание для отмены по таймауту (5 секунд)
        job = context.job_queue.run_once(
            cancel_input_timeout,
            when=5,
            data={'user_id': update.effective_user.id},
            chat_id=update.effective_chat.id,
            name=f"input_timeout_{update.effective_user.id}"
        )
        
        # Сохраняем задание для возможной отмены
        context.user_data['timeout_job'] = job
        
        await update.message.reply_text(
            "💪 <b>Введите количество отжиманий:</b>\n\n"
            "<i>Просто напишите число, например: 50</i>\n\n"
            "<i>У вас есть 5 секунд на ввод</i>\n"
            "<i>Для отмены нажмите /cancel</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )
    
    elif text == "📊 Статистика":
        total, stats = get_statistics('all')
        message = f"📊 <b>Статистика за всё время</b>\n\n"
        message += f"<b>Всего отжиманий:</b> {total} раз\n\n"
        
        if stats:
            for i, (user_id, name, user_total) in enumerate(stats, 1):
                if i <= 10:
                    message += f"{i}. {name} - {user_total} раз\n"
            if len(stats) > 10:
                message += f"\n...и ещё {len(stats) - 10} участников"
        else:
            message += "Пока нет данных об отжиманиях"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    elif text == "📈 Текущий месяц":
        total, stats = get_statistics('month')
        today = datetime.now()
        month_name = today.strftime('%B %Y')
        
        message = f"📈 <b>Статистика за {month_name}</b>\n\n"
        message += f"<b>Всего отжиманий:</b> {total} раз\n\n"
        
        if stats:
            for i, (user_id, name, user_total) in enumerate(stats, 1):
                if i <= 10:
                    message += f"{i}. {name} - {user_total} раз\n"
            if len(stats) > 10:
                message += f"\n...и ещё {len(stats) - 10} участников"
        else:
            message += "Пока нет данных за этот месяц"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    elif text == "🏆 Лидеры месяца":
        total, stats = get_statistics('month')
        today = datetime.now()
        month_name = today.strftime('%B %Y')
        
        if stats:
            message = f"🏆 <b>Лидеры {month_name}</b>\n\n"
            
            top_users = stats[:5]
            
            for i, (user_id, name, user_total) in enumerate(top_users, 1):
                if i == 1:
                    message += f"🥇 <b>{name}</b> - {user_total} отжиманий\n"
                elif i == 2:
                    message += f"🥈 <b>{name}</b> - {user_total} отжиманий\n"
                elif i == 3:
                    message += f"🥉 <b>{name}</b> - {user_total} отжиманий\n"
                else:
                    message += f"{i}. <b>{name}</b> - {user_total} отжиманий\n"
            
            message += f"\n<b>Всего участников:</b> {len(stats)}"
            message += f"\n<b>Общее количество:</b> {total}"
        else:
            message = "📊 Пока нет данных за этот месяц"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    elif text == "🎉 Победитель":
        total, stats = get_statistics('month')
        
        if stats:
            winner_id, winner_name, winner_total = stats[0]
            today = datetime.now()
            month_name = today.strftime('%B %Y')
            
            message = (
                f"🎉 <b>ПОБЕДИТЕЛЬ {month_name.upper()}</b>\n\n"
                f"🥇 <b>{winner_name}</b>\n\n"
                f"<b>Количество отжиманий:</b> {winner_total}\n"
                f"<b>Приз:</b> 2000 рублей\n\n"
                f"<i>Поздравляем победителя! 🎊</i>"
            )
        else:
            message = "📊 Пока нет данных за этот месяц"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    elif text == "👤 Моя статистика":
        await my_stats(update, context)
    
    elif text == "📅 Сегодня":
        await today_stats(update, context)
    
    else:
        # Игнорируем все другие текстовые сообщения
        # Не отправляем ответ, чтобы не засорять чат
        pass

# Обработчик ввода отжиманий
async def handle_pushup_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    # Проверяем, не отмена ли это
    if text.lower() in ['/cancel', 'отмена', 'cancel']:
        context.user_data.pop('waiting_for_count', None)
        context.user_data.pop('input_start_time', None)
        
        # Отменяем задание таймера если оно существует
        if 'timeout_job' in context.user_data:
            context.user_data['timeout_job'].schedule_removal()
            context.user_data.pop('timeout_job', None)
        
        await update.message.reply_text(
            "❌ Запись отменена.",
            reply_markup=MAIN_KEYBOARD
        )
        return
    
    try:
        count = int(text)
        if count <= 0:
            await update.message.reply_text(
                "❌ <b>Число должно быть больше 0.</b>\n"
                "Попробуйте еще раз (у вас 5 секунд):",
                parse_mode=ParseMode.HTML
            )
            # Сбрасываем таймер для нового ввода
            context.user_data['input_start_time'] = time.time()
            return
        
        if count > 10000:
            await update.message.reply_text(
                "😮 <b>Слишком большое число!</b>\n"
                "Пожалуйста, введите реальное количество (у вас 5 секунд):",
                parse_mode=ParseMode.HTML
            )
            # Сбрасываем таймер для нового ввода
            context.user_data['input_start_time'] = time.time()
            return
        
        # Записываем в базу
        add_pushups(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            count
        )
        
        # Сбрасываем состояние и отменяем таймер
        context.user_data.pop('waiting_for_count', None)
        context.user_data.pop('input_start_time', None)
        if 'timeout_job' in context.user_data:
            context.user_data['timeout_job'].schedule_removal()
            context.user_data.pop('timeout_job', None)
        
        await update.message.reply_text(
            f"✅ <b>Отлично! Записал {count} отжиманий за сегодня!</b>\n\n"
            f"<i>Продолжайте в том же духе! 💪</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_KEYBOARD
        )
        
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Пожалуйста, введите целое число.</b>\n"
            "Пример: 50\n\n"
            "<i>У вас 5 секунд на ввод</i>\n"
            "<i>Для отмены нажмите /cancel</i>",
            parse_mode=ParseMode.HTML
        )
        # Сбрасываем таймер для нового ввода
        context.user_data['input_start_time'] = time.time()

# Команда отмены
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_count'):
        context.user_data.pop('waiting_for_count', None)
        context.user_data.pop('input_start_time', None)
        
        # Отменяем задание таймера если оно существует
        if 'timeout_job' in context.user_data:
            context.user_data['timeout_job'].schedule_removal()
            context.user_data.pop('timeout_job', None)
        
        await update.message.reply_text(
            "✅ Запись отменена.",
            reply_markup=MAIN_KEYBOARD
        )
    else:
        await update.message.reply_text(
            "Нет активной операции для отмены.",
            reply_markup=MAIN_KEYBOARD
        )

# Личная статистика пользователя
async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('pushups.db')
    cursor = conn.cursor()
    
    # Общая статистика
    cursor.execute('''
    SELECT SUM(count) as total,
           COUNT(DISTINCT date) as days,
           AVG(count) as average,
           MAX(count) as max_count
    FROM pushups 
    WHERE user_id = ?
    ''', (user.id,))
    
    total_stats = cursor.fetchone()
    
    # Статистика за месяц
    today = datetime.now()
    first_day = today.replace(day=1).strftime('%Y-%m-%d')
    last_day = (today.replace(month=today.month+1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    cursor.execute('''
    SELECT SUM(count) as month_total,
           COUNT(DISTINCT date) as month_days
    FROM pushups 
    WHERE user_id = ? AND date BETWEEN ? AND ?
    ''', (user.id, first_day, last_day))
    
    month_stats = cursor.fetchone()
    
    # Статистика за сегодня
    today_str = today.strftime('%Y-%m-%d')
    cursor.execute('''
    SELECT SUM(count) as today_total
    FROM pushups 
    WHERE user_id = ? AND date = ?
    ''', (user.id, today_str))
    
    today_stats = cursor.fetchone()
    
    # Место в рейтинге за месяц
    cursor.execute('''
    SELECT user_id, SUM(count) as total
    FROM pushups 
    WHERE date BETWEEN ? AND ?
    GROUP BY user_id
    ORDER BY total DESC
    ''', (first_day, last_day))
    
    month_ranking = cursor.fetchall()
    user_rank = None
    for i, (uid, total) in enumerate(month_ranking, 1):
        if uid == user.id:
            user_rank = i
            break
    
    conn.close()
    
    total = total_stats[0] or 0
    days = total_stats[1] or 0
    average = total_stats[2] or 0
    max_count = total_stats[3] or 0
    month_total = month_stats[0] or 0
    month_days = month_stats[1] or 0
    today_total = today_stats[0] or 0
    
    user_name = user.username or user.first_name or "Участник"
    
    message = f"👤 <b>Личная статистика {user_name}</b>\n\n"
    
    message += f"<b>Сегодня:</b> {int(today_total)} отжиманий\n"
    message += f"<b>В этом месяце:</b> {int(month_total)} ({month_days} дней)\n"
    if user_rank:
        message += f"<b>Место в рейтинге:</b> {user_rank}\n"
    message += f"<b>Всего отжиманий:</b> {int(total)}\n"
    message += f"<b>Тренировочных дней:</b> {days}\n"
    if days > 0:
        message += f"<b>Среднее за тренировку:</b> {int(average)}\n"
        message += f"<b>Рекорд за раз:</b> {int(max_count)}\n"
    
    if days > 0:
        message += f"\n<b>Продолжайте в том же духе! 💪</b>"
    else:
        message += f"\n<b>Начните свою первую тренировку! 🏃‍♂️</b>"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Статистика за сегодня
async def today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('pushups.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('''
    SELECT COALESCE(username, first_name || ' ' || COALESCE(last_name, '')),
           SUM(count) as total
    FROM pushups 
    WHERE date = ?
    GROUP BY user_id
    ORDER BY total DESC
    ''', (today,))
    
    results = cursor.fetchall()
    conn.close()
    
    total_today = sum([row[1] for row in results]) if results else 0
    
    message = f"📅 <b>Статистика за сегодня ({today})</b>\n\n"
    message += f"<b>Всего отжиманий:</b> {total_today} раз\n\n"
    
    if results:
        message += "<b>Участники:</b>\n"
        for i, (name, user_total) in enumerate(results, 1):
            if i <= 10:
                message += f"{i}. {name} - {user_total} раз\n"
        if len(results) > 10:
            message += f"\n...и ещё {len(results) - 10} участников"
    else:
        message += "Сегодня еще никто не делал отжимания 😴\n\n"
        message += "Будьте первым! 💪"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Команда для еженедельного лидерборда
async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, stats = get_statistics('month')
    today = datetime.now()
    month_name = today.strftime('%B %Y')
    
    if stats:
        message = f"🏆 <b>Еженедельный лидерборд {month_name}</b>\n\n"
        
        top_users = stats[:5]
        
        for i, (user_id, name, user_total) in enumerate(top_users, 1):
            if i == 1:
                message += f"🥇 <b>{name}</b> - {user_total} отжиманий\n"
            elif i == 2:
                message += f"🥈 <b>{name}</b> - {user_total} отжиманий\n"
            elif i == 3:
                message += f"🥉 <b>{name}</b> - {user_total} отжиманий\n"
            else:
                message += f"{i}. <b>{name}</b> - {user_total} отжиманий\n"
        
        message += f"\n<b>Всего участников:</b> {len(stats)}"
        message += f"\n<b>Общее количество:</b> {total}"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("📊 Пока нет данных за этот месяц")

# Команда для общего рейтинга
async def all_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, stats = get_statistics('all')
    message = f"📊 <b>Общий рейтинг за всё время</b>\n\n"
    message += f"<b>Всего отжиманий:</b> {total} раз\n\n"
    
    if stats:
        message += "<b>Топ-10 участников:</b>\n"
        for i, (user_id, name, user_total) in enumerate(stats[:10], 1):
            message += f"{i}. {name} - {user_total} раз\n"
        
        if len(stats) > 10:
            message += f"\n...и ещё {len(stats) - 10} участников"
    else:
        message += "Пока нет данных об отжиманиях"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Команда помощи
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>📋 Доступные команды:</b>

/start - Показать главное меню с клавиатурой
/help - Эта справка
/weekly - Еженедельный лидерборд
/allstats - Общий рейтинг за всё время
/cancel - Отменить текущее действие

<b>🎯 Как пользоваться:</b>
1. Используйте кнопки внизу экрана
2. Нажмите "Записать тренировку"
3. Введите количество отжиманий в течение 5 секунд
4. Смотрите статистику через кнопки

<b>🏆 Призы:</b>
В конце месяца победитель получает 2000 рублей!

<b>📱 Кнопки всегда под рукой!</b>
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# Команда для сброса базы данных (только для администратора)
async def reset_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Замените '@Kovalevev' на ваш ID
    if str(user.id) == '@Kovalevev':  
        init_db()
        await update.message.reply_text("✅ База данных сброшена")
    else:
        await update.message.reply_text("❌ У вас нет прав для этой команды")

# Главная функция
def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("weekly", weekly))
    application.add_handler(CommandHandler("allstats", all_stats))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("reset", reset_db))
    
    # Обработчик всех текстовых сообщений
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )
    
    # Запуск бота
    print("=" * 50)
    print("🤖 Бот для учета отжиманий запущен!")
    print("📱 Работает на Android через Pydroid 3")
    print("=" * 50)
    print("\n🎯 Особенности этой версии:")
    print("✅ Постоянная клавиатура внизу экрана")
    print("✅ Проверка ввода только при ожидании числа")
    print("✅ Таймаут 5 секунд на ввод отжиманий")
    print("✅ Остальные сообщения игнорируются")
    print("=" * 50)
    print("\n💡 Совет:")
    print("1. Добавьте бота в группу")
    print("2. Назначьте администратором")
    print("3. Напишите в группе /start")
    print("4. Используйте кнопки для управления")
    print("=" * 50)
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        print("Проверьте интернет соединение и токен бота")

if __name__ == '__main__':
    main()
