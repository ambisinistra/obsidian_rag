import os

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram import F

from db_filling import ObsidianIndexer, DB_CONFIG

# Импортируйте ваш класс ObsidianIndexer и DB_CONFIG
# from your_module import ObsidianIndexer, DB_CONFIG

from dotenv import load_dotenv  # Импортируем функцию

# Загружаем переменные окружения из файла .env
load_dotenv()

# Конфигурация бота из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация бота
# Проверка, что токен был найден
if not BOT_TOKEN:
    logger.critical("Не найдена переменная окружения BOT_TOKEN. Бот не может быть запущен.")
    exit() # Или raise ValueError(...)
    
OBSIDIAN_DIR = "second_brain"  # Путь к вашей директории с заметками

# Глобальная переменная для индексера
indexer = None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def initialize_indexer():
    """Инициализация и запуск индексации при старте бота"""
    global indexer
    
    logger.info("Инициализация ObsidianIndexer...")
    indexer = ObsidianIndexer(
        obsidian_dir=OBSIDIAN_DIR,
        db_config=DB_CONFIG
    )
    
    # Раскомментируйте эту строку, если хотите начать с чистых таблиц
    # await indexer.raw_start()
    
    logger.info("Начинаем индексацию заметок Obsidian...")
    await indexer.index_all_files()
    logger.info("Индексация завершена!")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "🤖 Привет! Я бот для поиска по заметкам Obsidian.\n\n"
        "Просто отправь мне текст для поиска, и я найду похожие заметки!\n\n"
        "Команды:\n"
        "/start - показать это сообщение\n"
        "/help - справка\n"
        "/reindex - переиндексировать заметки"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Справка по использованию:\n\n"
        "1. Отправьте любое текстовое сообщение для поиска\n"
        "2. Бот найдет до 3 самых похожих фрагментов из ваших заметок\n"
        "3. Используйте /reindex для обновления индекса\n\n"
        "Пример: отправьте 'машинное обучение' для поиска заметок на эту тему"
    )


@dp.message(Command("reindex"))
async def cmd_reindex(message: Message):
    """Обработчик команды переиндексации"""
    global indexer
    
    await message.answer("🔄 Начинаю переиндексацию заметок...")
    
    try:
        if indexer is None:
            await initialize_indexer()
        else:
            await indexer.index_all_files()
        
        await message.answer("✅ Переиндексация завершена!")
        
    except Exception as e:
        logger.error(f"Ошибка при переиндексации: {e}")
        await message.answer(f"❌ Ошибка при переиндексации: {str(e)}")


@dp.message(F.text)
async def handle_search_query(message: Message):
    """Обработчик текстовых сообщений для поиска"""
    global indexer
    
    if indexer is None:
        await message.answer("⚠️ Индексер не инициализирован. Попробуйте /reindex")
        return
    
    query = message.text
    
    # Отправляем уведомление о начале поиска
    search_message = await message.answer("🔍 Ищу похожие заметки...")
    
    try:
        # Выполняем поиск
        results = await indexer.search_similar(query, limit=10)
        
        if not results:
            await search_message.edit_text("😔 Похожие заметки не найдены")
            return
        
        # Формируем ответ
        response_text = f"🎯 Найдено {len(results)} результатов для запроса: *{query}*\n\n"
        
        for i, result in enumerate(results, 1):
            file_name = result['file_path'].split('/')[-1]  # Получаем имя файла
            distance = result['distance']
            text_preview = result['text'][:200].replace('\n', ' ')
            
            response_text += f"*{i}. {file_name}*\n"
            response_text += f"📊 Релевантность: {(1-distance)*100:.1f}%\n"
            response_text += f"📝 Текст: {text_preview}...\n"
            response_text += f"📁 Путь: `{result['file_path']}`\n\n"
        
        # Разбиваем длинные сообщения
        if len(response_text) > 4000:
            # Отправляем по частям
            parts = []
            current_part = f"🎯 Найдено {len(results)} результатов для запроса: *{query}*\n\n"
            
            for i, result in enumerate(results, 1):
                file_name = result['file_path'].split('/')[-1]
                distance = result['distance']
                text_preview = result['text'][:200].replace('\n', ' ')
                
                part_text = f"*{i}. {file_name}*\n"
                part_text += f"📊 Релевантность: {(1-distance)*100:.1f}%\n"
                part_text += f"📝 Текст: {text_preview}...\n"
                part_text += f"📁 Путь: `{result['file_path']}`\n\n"
                
                if len(current_part + part_text) > 4000:
                    parts.append(current_part)
                    current_part = part_text
                else:
                    current_part += part_text
            
            if current_part:
                parts.append(current_part)
            
            # Отправляем первую часть, редактируя исходное сообщение
            await search_message.edit_text(parts[0], parse_mode="Markdown")
            
            # Отправляем остальные части как новые сообщения
            for part in parts[1:]:
                await message.answer(part, parse_mode="Markdown")
        else:
            await search_message.edit_text(response_text, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await search_message.edit_text(f"❌ Ошибка при поиске: {str(e)}")


async def on_startup():
    """Функция, вызываемая при запуске бота"""
    logger.info("Бот запускается...")
    await initialize_indexer()
    logger.info("Бот готов к работе!")


async def on_shutdown():
    """Функция, вызываемая при остановке бота"""
    logger.info("Бот завершает работу...")


async def main():
    """Основная функция для запуска бота"""
    try:
        # Инициализируем индексер при старте
        await on_startup()
        
        # Запускаем бота
        logger.info("Запускаем Telegram бота...")
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    # Установка необходимых пакетов:
    # pip install aiogram asyncpg aiohttp langchain
    
    asyncio.run(main())