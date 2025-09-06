import os
import asyncio
import logging
from datetime import datetime, timezone
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import json

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Словарь для хранения данных пользователей (в реальном приложении используйте базу данных)
user_data = {}

class ReflectionBot:
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        
        if user_id not in user_data:
            user_data[user_id] = {
                'reflections': [],
                'timezone': 'Europe/Moscow'
            }
        
        welcome_message = """
🌟 Добро пожаловать в бота для рефлексии!

Я помогу вам вести дневник и размышлять о прожитом дне.

Доступные команды:
/start - начать работу с ботом
/help - показать справку
/reflection - добавить рефлексию дня
/today - показать рефлексии за сегодня
/stats - статистика ваших рефлексий

Просто напишите мне свои мысли о дне, и я сохраню их!
        """
        
        await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help"""
        help_text = """
📋 Команды бота:

/start - начать работу с ботом
/help - показать эту справку
/reflection - добавить рефлексию дня
/today - показать рефлексии за сегодня
/stats - показать статистику

💡 Как пользоваться:
- Просто напишите свои мысли о дне
- Используйте /reflection для структурированной рефлексии
- Просматривайте свои записи командой /today

Бот сохраняет все ваши записи и помогает отслеживать прогресс!
        """
        await update.message.reply_text(help_text)

    async def reflection_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /reflection"""
        reflection_prompt = """
🤔 Время для рефлексии! Ответьте на несколько вопросов:

1. Что хорошего произошло сегодня?
2. Чему я научился(ась) сегодня?
3. За что я благодарен(на) сегодня?
4. Что можно улучшить завтра?
5. Какое у меня сейчас настроение и почему?

Отправьте свои размышления одним сообщением, я сохраню их как рефлексию дня.
        """
        await update.message.reply_text(reflection_prompt)

    async def today_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать рефлексии за сегодня"""
        user_id = update.effective_user.id
        
        if user_id not in user_data:
            user_data[user_id] = {'reflections': [], 'timezone': 'Europe/Moscow'}
            
        today = datetime.now(self.moscow_tz).date()
        today_reflections = [
            r for r in user_data[user_id]['reflections'] 
            if datetime.fromisoformat(r['timestamp']).date() == today
        ]
        
        if not today_reflections:
            await update.message.reply_text("📝 Сегодня у вас пока нет записей. Напишите что-нибудь!")
            return
            
        message = f"📅 Ваши размышления за {today.strftime('%d.%m.%Y')}:\n\n"
        
        for i, reflection in enumerate(today_reflections, 1):
            time = datetime.fromisoformat(reflection['timestamp']).strftime('%H:%M')
            message += f"🕐 {time}\n{reflection['text']}\n\n"
            
        await update.message.reply_text(message)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать статистику рефлексий"""
        user_id = update.effective_user.id
        
        if user_id not in user_data or not user_data[user_id]['reflections']:
            await update.message.reply_text("📊 У вас пока нет записей для статистики.")
            return
            
        reflections = user_data[user_id]['reflections']
        total_count = len(reflections)
        
        # Группируем по дням
        days = set()
        for reflection in reflections:
            date = datetime.fromisoformat(reflection['timestamp']).date()
            days.add(date)
            
        unique_days = len(days)
        
        if reflections:
            first_date = min(datetime.fromisoformat(r['timestamp']).date() for r in reflections)
            last_date = max(datetime.fromisoformat(r['timestamp']).date() for r in reflections)
            
            stats_message = f"""
📊 Ваша статистика рефлексий:

📝 Всего записей: {total_count}
📅 Дней с записями: {unique_days}
🗓 Первая запись: {first_date.strftime('%d.%m.%Y')}
🗓 Последняя запись: {last_date.strftime('%d.%m.%Y')}

Продолжайте в том же духе! 💪
            """
        else:
            stats_message = "📊 У вас пока нет записей для статистики."
            
        await update.message.reply_text(stats_message)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик текстовых сообщений"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if user_id not in user_data:
            user_data[user_id] = {'reflections': [], 'timezone': 'Europe/Moscow'}
        
        # Сохраняем рефлексию
        now = datetime.now(self.moscow_tz)
        reflection = {
            'text': message_text,
            'timestamp': now.isoformat(),
            'date': now.date().isoformat()
        }
        
        user_data[user_id]['reflections'].append(reflection)
        
        # Отправляем подтверждение
        confirmation_message = f"""
✅ Ваша рефлексия сохранена!

🕐 Время: {now.strftime('%H:%M, %d.%m.%Y')}
📝 Записей сегодня: {len([r for r in user_data[user_id]['reflections'] if r['date'] == now.date().isoformat()])}

Спасибо за то, что делитесь своими мыслями! 🙏
        """
        
        await update.message.reply_text(confirmation_message)

async def main():
    """Главная функция"""
    # Получаем токен бота из переменных окружения
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN не найден в переменных окружения")
        return
    
    # Создаем приложение
    application = Application.builder().token(bot_token).build()
    
    # Создаем экземпляр бота
    bot = ReflectionBot()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("reflection", bot.reflection_command))
    application.add_handler(CommandHandler("today", bot.today_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    # Запускаем бота
    logger.info("Запуск бота...")
    
    # Для деплоя на Render используем webhook
    PORT = int(os.environ.get('PORT', 8443))
    
    # Настройка webhook для деплоя
    webhook_url = os.getenv('WEBHOOK_URL')  # URL вашего приложения на Render
    
    if webhook_url:
        logger.info(f"Запуск с webhook на порту {PORT}")
        await application.bot.set_webhook(url=f"{webhook_url}/webhook")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{webhook_url}/webhook",
            secret_token="your-secret-token"
        )
    else:
        logger.info("Запуск в режиме polling")
        await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
