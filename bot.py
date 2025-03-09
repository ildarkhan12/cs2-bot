import os
import json
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Токен бота и конфигурация вебхука
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ID администратора и группы
ADMIN_ID = 113405030
GROUP_ID = -1002484381098
bot_username = "CS2RatingBot"

# Глобальные переменные для голосований
voting_active = False
breakthrough_voting_active = False
current_voting_participants = []
voting_message_id = None
breakthrough_message_id = None

# Константа авто-завершения голосования: 24 часа = 86400 секунд
AUTO_FINISH_DELAY = 86400

# Функции работы с данными
def migrate_players_data(data):
    for player in data['players']:
        if 'stats' not in player:
            player['stats'] = {}
        if 'awards' not in player:
            player['awards'] = {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0}
        if 'avg_rating' in player['stats']:
            del player['stats']['avg_rating']
        player['stats'].setdefault('mvp_count', player['awards'].get('mvp', 0))
        player['stats'].setdefault('games_played', 0)
        player['stats'].setdefault('votes_cast', 0)
        if 'rank_points' not in player['stats']:
            points = player['stats']['games_played'] * 5
            points += player['awards'].get('mvp', 0) * 25
            points += player['awards'].get('place1', 0) * 20
            points += player['awards'].get('place2', 0) * 15
            points += player['awards'].get('place3', 0) * 12
            points += player['awards'].get('breakthrough', 0) * 10
            player['stats']['rank_points'] = points
        update_rank(player)
        player['awards'].setdefault('breakthrough', 0)
    return data

def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            migrated_data = migrate_players_data(data)
            save_players(migrated_data)
            return migrated_data
    except FileNotFoundError:
        logger.warning("Файл players.json не найден, возвращаю пустые данные.")
        return {"players": []}
    except Exception as e:
        logger.exception("Ошибка при чтении players.json")
        return {"players": []}

def save_players(data):
    try:
        with open('players.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.exception("Ошибка при сохранении players.json")

def update_rank(player):
    points = player['stats'].get('rank_points', 0)
    if points >= 801:
        player['stats']['rank'] = "Майор"
    elif points >= 501:
        player['stats']['rank'] = "Капитан"
    elif points >= 301:
        player['stats']['rank'] = "Лейтенант"
    elif points >= 151:
        player['stats']['rank'] = "Сержант"
    elif points >= 51:
        player['stats']['rank'] = "Капрал"
    else:
        player['stats']['rank'] = "Рядовой"

# Функция авто-завершения голосования через 24 часа
async def auto_finish_voting():
    await asyncio.sleep(AUTO_FINISH_DELAY)
    if voting_active:
        for participant_id in current_voting_participants:
            try:
                await bot.send_message(participant_id, "⏰ Голосование завершено автоматически через 24 часа.")
            except Exception as e:
                logger.exception("Не удалось отправить уведомление участнику %s", participant_id)
        await check_voting_complete()
        logger.info("Голосование автоматически завершено по таймеру (24 часа)")

# Обработчик команды /start
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    # Если команда вызвана в группе, выводим сообщение с кнопкой-переадресацией в ЛС
    if message.chat.type != "private":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Перейти в ЛС", url=f"t.me/{bot_username}")]
        ])
        await message.reply("Это групповой чат. Для полноценного взаимодействия перейдите в личные сообщения с ботом.", reply_markup=keyboard)
        logger.info("Команда /start получена в группе от пользователя %s", message.from_user.id)
        return

    # Если в ЛС – показываем полноценное меню
    welcome_text = (
        "Салам, боец!\n"
        "Я бот вашей CS2-тусовки. Вот что я умею:\n"
        "🏆 Проводить голосования за рейтинг игроков (топ-10)\n"
        "🚀 Определять 'Прорыв вечера'\n"
        "🎖 Присуждать награды и звания (от Рядового до Майора)\n"
        "📊 Вести статистику (очки, награды, игры)\n\n"
        "ℹ️ Выбери действие ниже:"
    )
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Список команд", callback_data="help"),
            types.InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")
        ]
    ]
    if message.from_user.id == ADMIN_ID:
        inline_keyboard.extend([
            [
                types.InlineKeyboardButton(text="Управление игроками", callback_data="manage_players"),
                types.InlineKeyboardButton(text="Голосование за рейтинг", callback_data="start_voting_menu")
            ]
        ])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.reply(welcome_text, reply_markup=keyboard)
    logger.info("Отправлено приветственное сообщение пользователю %s", message.from_user.id)

# Обработчик для кнопки "Управление игроками" (для админа)
@dp.callback_query(lambda c: c.data == 'manage_players')
async def manage_players_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text="Добавить игрока", callback_data="add_player_prompt")],
        [types.InlineKeyboardButton(text="Удалить игрока", callback_data="remove_player_prompt")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выберите действие:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)
    logger.info("Администратор %s вызвал управление игроками", callback_query.from_user.id)

# Обработчики для подсказок по управлению игроками
@dp.callback_query(lambda c: c.data == 'add_player_prompt')
async def add_player_prompt(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Используйте команду /add_player [ID] [Имя] для добавления игрока.")
    logger.info("Подсказка по добавлению игрока отправлена админу %s", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data == 'remove_player_prompt')
async def remove_player_prompt(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Используйте команду /remove_player [ID] для удаления игрока.")
    logger.info("Подсказка по удалению игрока отправлена админу %s", callback_query.from_user.id)

# Команда для удаления игрока
@dp.message(Command(commands=['remove_player']))
async def remove_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
        return
    args = message.text.split(maxsplit=1)[1:]
    if len(args) < 1:
        await message.reply("ℹ️ Используй: /remove_player [ID]")
        return
    try:
        player_id = int(args[0])
        players_data = load_players()
        players_list = players_data['players']
        new_players_list = [p for p in players_list if p['id'] != player_id]
        if len(new_players_list) == len(players_list):
            await message.reply(f"❌ Игрок с ID {player_id} не найден!")
            return
        players_data['players'] = new_players_list
        save_players(players_data)
        await message.reply(f"✅ Игрок с ID {player_id} удалён!")
        logger.info("Удалён игрок с ID %s", player_id)
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

# Команда /add_player уже реализована ранее
@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply("ℹ️ Используй: /add_player [ID] [Имя]")
        return
    try:
        player_id = int(args[0])
        player_name = args[1]
        players_data = load_players()
        if any(p['id'] == player_id for p in players_data['players']):
            await message.reply(f"❌ Игрок с ID {player_id} уже существует!")
            return
        players_data['players'].append({
            "id": player_id,
            "name": player_name,
            "ratings": [],
            "played_last_game": False,
            "awards": {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0},
            "stats": {"mvp_count": 0, "games_played": 0, "votes_cast": 0, "rank_points": 0, "rank": "Рядовой"}
        })
        save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
        logger.info("Добавлен игрок %s (ID: %s)", player_name, player_id)
    except ValueError:
        await message.reply("❌ ID должен быть числом!")
    except Exception as e:
        logger.exception("Ошибка при добавлении игрока")

# Команда /leaderboard для отображения рейтинга игроков (Markdown)
@dp.message(Command(commands=['leaderboard']))
async def leaderboard(message: types.Message):
    players = load_players()['players']
    if not players:
        await message.reply("Список игроков пуст!")
        return
    sorted_players = sorted(players, key=lambda p: p['stats'].get('rank_points', 0), reverse=True)
    text = "*Лидерборд игроков:*\n\n"
    for i, p in enumerate(sorted_players, 1):
        text += f"{i}. *{p['name']}* — {p['stats'].get('rank_points', 0)} очков\n"
    await message.reply(text, parse_mode="Markdown")
    logger.info("Лидерборд запрошен пользователем %s", message.from_user.id)

# Остальные обработчики голосования, статистики и т.д. оставляем без изменений
# (код голосования, callback_query для оценок, завершения голосования, прорыва вечера и т.д.)

# Например, ниже приведён обработчик для callback "help"
@dp.callback_query(lambda c: c.data == 'help')
async def callback_help(callback_query: types.CallbackQuery):
    help_text = (
        "Список доступных команд:\n"
        "/start - запустить бота\n"
        "/my_stats - посмотреть свою статистику\n"
        "/add_player - добавить игрока (только для админа)\n"
        "/remove_player - удалить игрока (только для админа)\n"
        "/leaderboard - посмотреть текущий рейтинг игроков\n"
        "# Прочие команды можно добавить по необходимости."
    )
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, help_text)
    logger.info("Пользователь %s запросил справку", callback_query.from_user.id)

# Прочие обработчики (для голосования, прорыва вечера и т.д.) остаются без изменений…
# [Здесь должен идти весь остальной код, реализующий логику голосований, уведомлений, авто-завершения и т.п.]

# Настройка вебхука и запуск
async def on_startup(dispatcher: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Бот запущен с вебхуком: %s", WEBHOOK_URL)

async def on_shutdown(dispatcher: Dispatcher):
    await bot.delete_webhook()
    logger.info("Бот остановлен")

async def main():
    app = web.Application()
    webhook_request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_request_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info("Сервер запущен на порту %s", os.getenv('PORT', 8080))
    
    try:
        await asyncio.Event().wait()  # Держим приложение запущенным
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
