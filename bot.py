import asyncio
import logging
import json
import os
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
import sqlite3
from dataclasses import dataclass, asdict
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes, 
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = '8343261083:AAFDsi3V2yv3dduTx3KzucIjYedhTOyDoLs'
DATABASE_PATH = 'reflections.db'

@dataclass
class DailyReflection:
    date: str
    user_id: int
    best_moment: Optional[str] = None
    gratitude: Optional[str] = None
    day_rating: Optional[int] = None
    tomorrow_focus: Optional[str] = None
    response_time: Optional[str] = None
    mood_context: Optional[str] = None

class DialogState:
    WAITING_BEST_MOMENT = "waiting_best_moment"
    WAITING_GRATITUDE = "waiting_gratitude" 
    WAITING_RATING = "waiting_rating"
    WAITING_TOMORROW = "waiting_tomorrow"
    COMPLETED = "completed"

class ReflectionBot:
    def __init__(self, token: str):
        self.token = token
        self.application = None
        self.scheduler = AsyncIOScheduler()
        self.init_database()
        
        # Банк приветствий
        self.greetings = {
            'classic': [
                "Привет! Как прошёл твой день? 🌙",
                "Время для вечерней рефлексии ✨",
                "День завершается... поделись мыслями! 💭"
            ],
            'weekday': {
                0: "Новая неделя началась, как первый день?",
                4: "Неделя близится к концу!",
                5: "Как проводишь выходной?",
                6: "Как проводишь выходной?"
            },
            'seasonal': [
                "Уютный зимний вечер для размышлений",
                "Дождливый день располагает к рефлексии", 
                "Солнечный день завершается"
            ]
        }
        
        # Состояния пользователей для диалога
        self.user_states = {}
        
        # Вопросы для диалога
        self.dialog_questions = {
            DialogState.WAITING_BEST_MOMENT: {
                'question': "Что самое ценное произошло сегодня? ✨\n\nПоделись хотя бы одним моментом, который порадовал или запомнился:",
                'next_state': DialogState.WAITING_GRATITUDE
            },
            DialogState.WAITING_GRATITUDE: {
                'question': "Понял! А теперь о благодарности 💛\n\nКому или за что ты сегодня благодарен/благодарна?",
                'next_state': DialogState.WAITING_RATING
            },
            DialogState.WAITING_RATING: {
                'question': "Отлично! 📊\n\nА теперь оцени день от 1 до 10 - как прошёл этот день в целом?",
                'next_state': DialogState.WAITING_TOMORROW
            },
            DialogState.WAITING_TOMORROW: {
                'question': "И последний вопрос! 🎯\n\nЧто главное хочешь сделать или на чём сосредоточиться завтра?",
                'next_state': DialogState.COMPLETED
            }
        }
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                user_id INTEGER,
                best_moment TEXT,
                gratitude TEXT,
                day_rating INTEGER,
                tomorrow_focus TEXT,
                response_time TEXT,
                mood_context TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                timezone TEXT DEFAULT 'UTC',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_reflection(self, reflection: DailyReflection):
        """Сохранение рефлексии в базу данных"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже запись за этот день
        cursor.execute(
            'SELECT id FROM reflections WHERE date = ? AND user_id = ?',
            (reflection.date, reflection.user_id)
        )
        existing = cursor.fetchone()
        
        if existing:
            # Обновляем существующую запись
            cursor.execute('''
                UPDATE reflections 
                SET best_moment = COALESCE(?, best_moment),
                    gratitude = COALESCE(?, gratitude),
                    day_rating = COALESCE(?, day_rating),
                    tomorrow_focus = COALESCE(?, tomorrow_focus),
                    response_time = COALESCE(?, response_time),
                    mood_context = COALESCE(?, mood_context)
                WHERE id = ?
            ''', (*[getattr(reflection, field) for field in 
                   ['best_moment', 'gratitude', 'day_rating', 'tomorrow_focus', 
                    'response_time', 'mood_context']], existing[0]))
        else:
            # Создаём новую запись
            cursor.execute('''
                INSERT INTO reflections 
                (date, user_id, best_moment, gratitude, day_rating, tomorrow_focus, response_time, mood_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (reflection.date, reflection.user_id, reflection.best_moment,
                  reflection.gratitude, reflection.day_rating, reflection.tomorrow_focus,
                  reflection.response_time, reflection.mood_context))
        
        conn.commit()
        conn.close()
    
    def get_user_reflections(self, user_id: int, days: int = 7) -> List[Dict]:
        """Получение рефлексий пользователя за последние дни"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days-1)
        
        cursor.execute('''
            SELECT * FROM reflections 
            WHERE user_id = ? AND date BETWEEN ? AND ?
            ORDER BY date DESC
        ''', (user_id, start_date.isoformat(), end_date.isoformat()))
        
        columns = [description[0] for description in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        conn.close()
        return results
    
    def get_user_diary(self, user_id: int, limit: int = 30) -> List[Dict]:
        """Получение истории как дневника (все записи подряд по датам)"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM reflections 
            WHERE user_id = ?
            ORDER BY date DESC
            LIMIT ?
        ''', (user_id, limit))
        
        columns = [description[0] for description in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        conn.close()
        return results
    
    def format_diary_entry(self, reflection: Dict) -> str:
        """Форматирование одной записи дневника"""
        date_obj = datetime.strptime(reflection['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime('%d.%m.%Y')
        weekday_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        weekday = weekday_names[date_obj.weekday()]
        
        entry = f"📅 **{formatted_date} ({weekday})**\n\n"
        
        if reflection['best_moment']:
            entry += f"✨ **Лучший момент:**\n{reflection['best_moment']}\n\n"
        
        if reflection['gratitude']:
            entry += f"💛 **Благодарность:**\n{reflection['gratitude']}\n\n"
        
        if reflection['day_rating']:
            rating_emoji = "💪" if reflection['day_rating'] >= 7 else "💙" if reflection['day_rating'] >= 5 else "🫂"
            entry += f"📊 **Оценка дня:** {reflection['day_rating']}/10 {rating_emoji}\n\n"
        
        if reflection['tomorrow_focus']:
            entry += f"🎯 **Планы на завтра:**\n{reflection['tomorrow_focus']}\n\n"
        
        return entry + "─" * 30 + "\n\n"
    
    def get_greeting(self) -> str:
        """Получение приветствия с учётом дня недели"""
        today = datetime.now()
        weekday = today.weekday()
        
        # Специальные приветствия для определённых дней
        if weekday in self.greetings['weekday']:
            return self.greetings['weekday'][weekday]
        
        # Случайное классическое приветствие
        return random.choice(self.greetings['classic'])
    
    def get_initial_message(self, rating: Optional[int] = None) -> str:
        """Формирование начального сообщения для рефлексии"""
        greeting = self.get_greeting()
        today_date = datetime.now().strftime("%d.%m.%Y")
        
        # Адаптация сообщения в зависимости от предыдущей оценки
        if rating and rating <= 4:
            message = f"""Доброй ночи! 💙

📅 {today_date}

Чувствую, что вчера было непросто. Но ты справился - это уже победа!

Давай найдём хоть маленькие светлые моменты в сегодняшнем дне..."""
        
        elif rating and rating >= 8:
            message = f"""{greeting}

📅 {today_date}

Чувствую твою хорошую энергию! 🌟

Расскажи мне об этом дне..."""
        
        else:
            message = f"""{greeting}

📅 {today_date}

Время для нашей вечерней традиции! Расскажи мне об этом дне..."""
        
        return message
    
    def generate_weekly_analytics(self, user_id: int) -> str:
        """Генерация еженедельной аналитики"""
        reflections = self.get_user_reflections(user_id, 7)
        
        if not reflections:
            return "Привет! На этой неделе мы ещё не общались. Начнём новую традицию? ✨"
        
        # Подсчёт статистики
        ratings = [r['day_rating'] for r in reflections if r['day_rating']]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        high_days = len([r for r in ratings if r >= 7])
        
        # Топ моменты
        best_moments = [r['best_moment'] for r in reflections if r['best_moment']][:2]
        
        # Анализ благодарностей
        gratitudes = [r['gratitude'] for r in reflections if r['gratitude']]
        
        # Планы
        plans = [r['tomorrow_focus'] for r in reflections if r['tomorrow_focus']]
        
        week_start = (datetime.now() - timedelta(days=6)).strftime("%d.%m")
        week_end = datetime.now().strftime("%d.%m.%Y")
        
        message = f"""Привет! Неделя подошла к концу ✨

📅 НЕДЕЛЯ {week_start} - {week_end}

📊 НЕДЕЛЯ В ЦИФРАХ:
Средняя оценка: {avg_rating:.1f}/10
Дней выше 7: {high_days} из {len(ratings)}
Всего записей: {len(reflections)}

🌟 ТОП-МОМЕНТЫ НЕДЕЛИ:"""
        
        for i, moment in enumerate(best_moments, 1):
            message += f"\n• {moment}"
        
        if gratitudes:
            message += f"\n\n💛 БЛАГОДАРНОСТИ:\nВсего упоминаний: {len(gratitudes)}"
        
        if plans:
            message += f"\n\n🎯 ПЛАНЫ И ДОСТИЖЕНИЯ:\nЗапланировано целей: {len(plans)}"
        
        message += "\n\n✨ НА НОВУЮ НЕДЕЛЮ:\nПродолжай замечать хорошее в каждом дне! Ты молодец!"
        
        return message
    
    async def setup_bot_commands(self):
        """Настройка меню команд бота"""
        commands = [
            BotCommand("start", "🌟 Начать работу с ботом"),
            BotCommand("reflect", "💭 Начать диалог рефлексии"),
            BotCommand("diary", "📖 Посмотреть мой дневник"),
            BotCommand("analytics", "📊 Статистика за неделю"),
            BotCommand("help", "❓ Помощь")
        ]
        
        await self.application.bot.set_my_commands(commands)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        # Регистрируем пользователя
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)',
            (user_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        
        welcome_message = """Привет! 🌟

Я твой помощник для ежедневной рефлексии. Каждый день в 23:00 я буду задавать тебе вопросы о дне, и мы будем вести настоящий диалог!

🗣 КАК ЭТО РАБОТАЕТ:
• Я задаю вопрос
• Ты отвечаешь 
• Я перехожу к следующему вопросу
• И так пока не обсудим весь день!

💬 МОИ ВОПРОСЫ:
• О лучшем моменте дня ✨
• О благодарности 💛  
• Оценка дня от 1 до 10 📊
• Планы на завтра 🎯

📅 А по воскресеньям - аналитика недели с датами!

📱 **КОМАНДЫ В МЕНЮ:**
💭 /reflect - начать диалог прямо сейчас
📖 /diary - посмотреть свой дневник
📊 /analytics - статистика за неделю  
❓ /help - подробная справка

Все команды теперь доступны в меню внизу! 👇

Готов к живому общению? 😊"""
        
        await update.message.reply_text(welcome_message)
    
    async def reflect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ручной запуск рефлексии"""
        user_id = update.effective_user.id
        await self.start_reflection_dialog(user_id, update.message.chat_id)
    
    async def diary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать дневник пользователя"""
        user_id = update.effective_user.id
        diary_entries = self.get_user_diary(user_id, 30)  # Последние 30 записей
        
        if not diary_entries:
            message = """📖 **МОЙ ДНЕВНИК**

Пока здесь пусто... 🌱

Начни вести дневник размышлений уже сегодня! Напиши /reflect или дождись автоматического сообщения в 23:00.

Каждый день - это новая страница твоей истории! ✨"""
            
            await update.message.reply_text(message)
            return
        
        # Группируем по месяцам для удобства
        current_month = ""
        diary_text = "📖 **МОЙ ДНЕВНИК РАЗМЫШЛЕНИЙ**\n\n"
        
        for entry in reversed(diary_entries[-10:]):  # Показываем последние 10 записей в хронологическом порядке
            entry_date = datetime.strptime(entry['date'], '%Y-%m-%d')
            entry_month = entry_date.strftime('%B %Y')
            
            # Добавляем заголовок месяца
            if entry_month != current_month:
                diary_text += f"🗓 **{entry_month.upper()}**\n\n"
                current_month = entry_month
            
            diary_text += self.format_diary_entry(entry)
        
        # Если записей больше 10, добавляем информацию об этом
        total_entries = len(diary_entries)
        if total_entries > 10:
            diary_text += f"📚 И ещё {total_entries - 10} записей в твоём дневнике!\n\n"
        
        diary_text += f"💫 **Всего записей в дневнике: {total_entries}**\n\n"
        diary_text += "Продолжай вести дневник размышлений! Каждая запись - это шаг к самопознанию. 🌟"
        
        # Разбиваем на части если слишком длинное сообщение
        if len(diary_text) > 4096:
            parts = []
            current_part = "📖 **МОЙ ДНЕВНИК РАЗМЫШЛЕНИЙ**\n\n"
            
            for entry in reversed(diary_entries[-5:]):  # Показываем меньше записей
                entry_formatted = self.format_diary_entry(entry)
                if len(current_part + entry_formatted) > 4000:
                    parts.append(current_part)
                    current_part = entry_formatted
                else:
                    current_part += entry_formatted
            
            parts.append(current_part)
            parts[-1] += f"\n💫 **Всего записей: {total_entries}**"
            
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(diary_text)
    
    async def start_reflection_dialog(self, user_id: int, chat_id: int):
        """Начало диалога рефлексии"""
        # Получаем последнюю оценку для адаптации приветствия
        recent_reflections = self.get_user_reflections(user_id, 1)
        last_rating = recent_reflections[0]['day_rating'] if recent_reflections else None
        
        # Создаём новую рефлексию
        today_date = datetime.now().date().isoformat()
        
        self.user_states[user_id] = {
            'dialog_state': DialogState.WAITING_BEST_MOMENT,
            'current_reflection': DailyReflection(
                date=today_date,
                user_id=user_id,
                response_time=datetime.now().isoformat()
            ),
            'chat_id': chat_id
        }
        
        # Отправляем приветствие
        greeting_message = self.get_initial_message(last_rating)
        
        # Первый вопрос
        first_question = self.dialog_questions[DialogState.WAITING_BEST_MOMENT]['question']
        
        keyboard = [[InlineKeyboardButton("Пропустить этот вопрос", callback_data="skip_question")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        full_message = f"{greeting_message}\n\n{first_question}"
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=full_message,
            reply_markup=reply_markup
        )
    
    async def analytics_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать аналитику за неделю"""
        user_id = update.effective_user.id
        analytics = self.generate_weekly_analytics(user_id)
        await update.message.reply_text(analytics)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Помощь"""
        help_text = """🤖 **ПОМОЩЬ ПО БОТУ РЕФЛЕКСИИ**

Теперь мы ведём настоящий диалог! 🗣

🕚 **ЕЖЕДНЕВНО В 23:00** я начну разговор:
1. Сначала поприветствую и спрошу о лучшем моменте дня ✨
2. После твоего ответа - о благодарности 💛
3. Затем попрошу оценить день 📊  
4. И наконец - о планах на завтра 🎯

📅 **Все записи сохраняются с датами в твой личный дневник!**

📊 **ПО ВОСКРЕСЕНЬЯМ В 20:00** - подробная аналитика недели

📱 **КОМАНДЫ В МЕНЮ:**
🌟 **/start** - знакомство с ботом
💭 **/reflect** - начать диалог прямо сейчас  
📖 **/diary** - посмотреть свой дневник размышлений
📊 **/analytics** - статистика за неделю
❓ **/help** - эта справка

🗣 **КАК ПРОХОДИТ ДИАЛОГ:**
• Отвечай естественно, как будто говоришь с другом
• Можешь пропустить любой вопрос кнопкой "Пропустить"
• Я буду ждать твоего ответа и переходить к следующему вопросу
• В любой момент можешь написать что-то своё - я пойму!

📖 **О ДНЕВНИКЕ:**
• Все твои ответы сохраняются как записи дневника
• Можешь в любое время посмотреть свою историю
• Записи идут по датам, как настоящий дневник
• Это поможет увидеть свой прогресс и паттерны

Живое общение + личный дневник = путь к самопознанию! 💛

Все команды доступны в меню внизу экрана! 👇"""
        
        await update.message.reply_text(help_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений в диалоге"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Проверяем, ведём ли мы диалог с пользователем
        if user_id not in self.user_states:
            await update.message.reply_text(
                "Понял! А как насчёт вечерней рефлексии? 😊\n\nНапиши /reflect чтобы начать наш диалог!\n\nИли загляни в свой /diary 📖"
            )
            return
        
        user_state = self.user_states[user_id]
        current_state = user_state['dialog_state']
        reflection = user_state['current_reflection']
        
        # Сохраняем ответ в зависимости от текущего состояния
        if current_state == DialogState.WAITING_BEST_MOMENT:
            reflection.best_moment = text
            response = f"Прекрасно! 🌟\n\nЗаписал: \"{text}\""
            
        elif current_state == DialogState.WAITING_GRATITUDE:
            reflection.gratitude = text
            response = f"Как важно помнить о благодарности! 💛\n\nЗаписал: \"{text}\""
            
        elif current_state == DialogState.WAITING_RATING:
            # Ищем число от 1 до 10
            import re
            rating_match = re.search(r'\b([1-9]|10)\b', text)
            if rating_match:
                reflection.day_rating = int(rating_match.group(1))
                rating_emoji = "💪" if reflection.day_rating >= 7 else "💙" if reflection.day_rating >= 5 else "🫂"
                response = f"Понял - {reflection.day_rating}/10 {rating_emoji}\n\nЗаписал: \"{text}\""
            else:
                response = f"Записал твой ответ! 📝\n\n\"{text}\"\n\n(Если хочешь указать точную оценку числом от 1 до 10, можешь добавить)"
                
        elif current_state == DialogState.WAITING_TOMORROW:
            reflection.tomorrow_focus = text
            response = f"Отличные планы! 🎯\n\nЗаписал: \"{text}\""
        
        # Определяем следующий шаг
        if current_state in self.dialog_questions:
            next_state = self.dialog_questions[current_state]['next_state']
            
            if next_state == DialogState.COMPLETED:
                # Завершаем диалог
                self.save_reflection(reflection)
                del self.user_states[user_id]
                
                completion_message = f"""{response}

✨ **ДЕНЬ ЗАВЕРШЁН!**

Спасибо за искренний разговор! Все твои мысли сохранены в дневник с датой {datetime.now().strftime('%d.%m.%Y')}.

📖 Посмотреть свои записи: /diary
📊 Статистика недели: /analytics

Увидимся завтра вечером для нового диалога! 💛

Сладких снов! 🌙"""
                
                await update.message.reply_text(completion_message)
                
            else:
                # Переходим к следующему вопросу
                user_state['dialog_state'] = next_state
                next_question = self.dialog_questions[next_state]['question']
                
                keyboard = [[InlineKeyboardButton("Пропустить этот вопрос", callback_data="skip_question")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                full_message = f"{response}\n\n{next_question}"
                
                await update.message.reply_text(full_message, reply_markup=reply_markup)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка inline кнопок"""
        query = update.callback_query
        user_id = query.from_user.id
        
        if query.data == "skip_question":
            if user_id not in self.user_states:
                await query.answer("Диалог уже завершён")
                return
                
            user_state = self.user_states[user_id]
            current_state = user_state['dialog_state']
            
            # Переходим к следующему вопросу
            if current_state in self.dialog_questions:
                next_state = self.dialog_questions[current_state]['next_state']
                
                if next_state == DialogState.COMPLETED:
                    # Завершаем диалог
                    reflection = user_state['current_reflection']
                    self.save_reflection(reflection)
                    del self.user_states[user_id]
                    
                    await query.answer()
                    await query.edit_message_text(
                        f"Хорошо, пропускаем! ✨\n\nДень завершён. Спасибо за разговор!\n\nВсе ответы сохранены в дневник с датой {datetime.now().strftime('%d.%m.%Y')}.\n\n📖 Посмотреть дневник: /diary\n📊 Статистика: /analytics\n\nУвидимся завтра! 💛"
                    )
                    
                else:
                    # Переходим к следующему вопросу
                    user_state['dialog_state'] = next_state
                    next_question = self.dialog_questions[next_state]['question']
                    
                    keyboard = [[InlineKeyboardButton("Пропустить этот вопрос", callback_data="skip_question")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.answer()
                    await query.edit_message_text(
                        f"Хорошо, пропускаем! ✨\n\n{next_question}",
                        reply_markup=reply_markup
                    )
    
    async def send_daily_reflection(self):
        """Отправка ежедневной рефлексии всем пользователям"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        
        for (user_id,) in users:
            try:
                await self.start_reflection_dialog(user_id, user_id)
                
            except Exception as e:
                logger.error(f"Ошибка отправки daily reflection пользователю {user_id}: {e}")
    
    async def send_weekly_analytics(self):
        """Отправка еженедельной аналитики всем пользователям"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        
        for (user_id,) in users:
            try:
                analytics = self.generate_weekly_analytics(user_id)
                await self.application.bot.send_message(chat_id=user_id, text=analytics)
                
            except Exception as e:
                logger.error(f"Ошибка отправки weekly analytics пользователю {user_id}: {e}")
    
    async def setup_application(self):
        """Настройка приложения"""
        self.application = Application.builder().token(self.token).build()
        
        # Регистрация обработчиков
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("reflect", self.reflect_command))
        self.application.add_handler(CommandHandler("diary", self.diary_command))
        self.application.add_handler(CommandHandler("analytics", self.analytics_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Настраиваем меню команд
        await self.setup_bot_commands()
        
        # Настройка планировщика
        self.scheduler.add_job(
            self.send_daily_reflection,
            CronTrigger(hour=23, minute=0),
            id='daily_reflection'
        )
        
        self.scheduler.add_job(
            self.send_weekly_analytics,
            CronTrigger(day_of_week=6, hour=20, minute=0),  # Воскресенье в 20:00
            id='weekly_analytics'
        )
    
    async def run(self):
        """Запуск бота"""
        await self.setup_application()
        
        # Запускаем планировщик
        self.scheduler.start()
        logger.info("Планировщик запущен")
        
        # Запускаем бота
        logger.info("Запуск бота...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        try:
            # Держим бота в работе
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            # Корректная остановка
            self.scheduler.shutdown()
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

def main():
    """Главная функция"""
    bot = ReflectionBot(BOT_TOKEN)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("👋 Бот остановлен пользователем")

if __name__ == "__main__":
    main()