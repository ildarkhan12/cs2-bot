import os
import json
import asyncio
import logging
import aiofiles
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
bot_username = "CS2_Team_Bot"

# Глобальные переменные для голосований
voting_active = False
breakthrough_voting_active = False
current_voting_participants = []
voting_message_id = None
breakthrough_message_id = None
voting_timer_message_id = None
breakthrough_timer_message_id = None
voted_users = []
voted_breakthrough_users = []

# Глобальный замок для доступа к файлу и переменная для таймера авто-завершения
file_lock = asyncio.Lock()
auto_finish_task = None

# Константа авто-завершения голосования: 24 часа = 86400 секунд
AUTO_FINISH_DELAY = 86400

# --- Функции работы с данными ---

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

async def load_players():
    async with file_lock:
        try:
            async with aiofiles.open('players.json', mode='r', encoding='utf-8') as f:
                contents = await f.read()
                data = json.loads(contents)
                migrated_data = migrate_players_data(data)
                await save_players(migrated_data)
                return migrated_data
        except FileNotFoundError:
            logger.warning("Файл players.json не найден, возвращаю пустые данные.")
            return {"players": []}
        except Exception as e:
            logger.exception("Ошибка при чтении players.json")
            return {"players": []}

async def save_players(data):
    async with file_lock:
        try:
            async with aiofiles.open('players.json', mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=4))
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

def get_average_rating(player):
    return (sum(player['ratings']) / len(player['ratings'])) if player['ratings'] else 0

# --- Функция авто-завершения голосования ---
async def auto_finish_voting():
    try:
        await asyncio.sleep(AUTO_FINISH_DELAY)
        if voting_active:
            for participant_id in current_voting_participants:
                try:
                    await bot.send_message(participant_id, "⏰ Голосование завершено автоматически через 24 часа.")
                except Exception as e:
                    logger.exception("Не удалось отправить уведомление участнику %s", participant_id)
            await check_voting_complete()
            logger.info("Голосование автоматически завершено по таймеру (24 часа)")
    except asyncio.CancelledError:
        logger.info("Таймер авто-завершения голосования отменён")
        raise

# --- Таймер для голосования ---
async def update_timer(chat_id, message_id, duration, voting_type="основное"):
    global voting_active, breakthrough_voting_active
    start_time = asyncio.get_event_loop().time()
    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        remaining = max(0, duration - int(elapsed))
        minutes, seconds = divmod(remaining, 60)
        hours, minutes = divmod(minutes, 60)
        timer_text = (
            f"⏳ *Время до конца {voting_type} голосования:*\n"
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        )
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=timer_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning("Не удалось обновить таймер: %s", e)
            break
        if remaining <= 0:
            if voting_type == "основное" and voting_active:
                await check_voting_complete()
            elif voting_type == "Прорыв вечера" and breakthrough_voting_active:
                await check_breakthrough_voting_complete()
            break
        await asyncio.sleep(300)  # Обновление каждые 5 минут

# --- Команды и обработчики ---

@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    if message.chat.type != "private":
        group_greeting = (
            "Салам, боец!\n"
            "Я бот вашей CS2-тусовки.\n"
            "ℹ️ Пошли в ЛС для управления:"
        )
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Перейти в ЛС", url=f"t.me/{bot_username}")]
        ])
        await message.reply(group_greeting, reply_markup=keyboard)
        return
    welcome_text = (
        "Салам, боец!\n"
        "Я бот вашей CS2-тусовки. Выбери действие:"
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
                types.InlineKeyboardButton(text="Голосование", callback_data="start_voting_menu")
            ]
        ])
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.reply(welcome_text, reply_markup=keyboard)
    logger.info("Отправлено приветственное сообщение пользователю %s", message.from_user.id)

@dp.callback_query(lambda c: c.data == 'help')
async def help_handler(callback_query: types.CallbackQuery):
    help_text = (
        "*Команды бота:*\n\n"
        "*/start* - Начать работу\n"
        "*/my_stats* - Ваша статистика\n"
        "*/leaderboard* - Топ игроков\n"
        "*/game_players* - Участники последней игры\n\n"
        "*Для админа:*\n"
        "*/add_player [ID] [Имя]* - Добавить игрока\n"
        "*/remove_player [ID]* - Удалить игрока\n"
        "*/start_game [ID1 ID2 ...]* - Начать игру\n"
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
    ])
    await bot.send_message(callback_query.from_user.id, help_text, parse_mode="Markdown", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'my_stats')
async def my_stats_callback(callback_query: types.CallbackQuery):
    logger.info("Получен callback для 'my_stats' от пользователя %s", callback_query.from_user.id)
    user_id = callback_query.from_user.id
    players_data = await load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (
            "*Ваша статистика:*\n\n"
            f"• *Звание:* {stats.get('rank', 'Рядовой')}\n"
            f"• *Очки:* {stats.get('rank_points', 0)}\n"
            f"• *Игр сыграно:* {stats.get('games_played', 0)}\n"
            f"• *MVP:* {awards.get('mvp', 0)} раз\n"
            f"• *1st:* {awards.get('place1', 0)} раз\n"
            f"• *2nd:* {awards.get('place2', 0)} раз\n"
            f"• *3rd:* {awards.get('place3', 0)} раз\n"
            f"• *Прорыв вечера:* {awards.get('breakthrough', 0)} раз\n"
        )
        await bot.send_message(callback_query.from_user.id, response, parse_mode="Markdown")
    else:
        await bot.send_message(callback_query.from_user.id, "❌ Вы не в списке игроков!")
    await bot.answer_callback_query(callback_query.id)
    logger.info("Статистика запрошена через кнопку пользователем %s", user_id)

@dp.callback_query(lambda c: c.data == 'manage_players')
async def manage_players_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text="Добавить игрока", callback_data="add_player_prompt")],
        [types.InlineKeyboardButton(text="Удалить игрока", callback_data="remove_player_prompt")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выберите действие:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'add_player_prompt')
async def add_player_prompt(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Используйте команду /add_player [ID] [Имя] для добавления игрока.")

@dp.callback_query(lambda c: c.data == 'remove_player_prompt')
async def remove_player_prompt(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = await load_players()
    players = players_data['players']
    if not players:
        await bot.send_message(callback_query.from_user.id, "❌ Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']} (ID: {p['id']})", callback_data=f"confirm_remove_{p['id']}")]
        for p in players
    ]
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_players")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выберите игрока для удаления:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

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
        inline_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Да", callback_data=f"confirm_remove_{player_id}")],
            [types.InlineKeyboardButton(text="Нет", callback_data="cancel_remove")]
        ])
        await message.reply(f"Вы уверены, что хотите удалить игрока с ID {player_id}?", reply_markup=inline_keyboard)
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

@dp.callback_query(lambda c: c.data.startswith('confirm_remove_'))
async def confirm_remove(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    try:
        player_id = int(callback_query.data.split('_')[2])
        players_data = await load_players()
        players_list = players_data['players']
        new_players_list = [p for p in players_list if p['id'] != player_id]
        if len(new_players_list) == len(players_list):
            await bot.send_message(callback_query.from_user.id, f"❌ Игрок с ID {player_id} не найден!")
            await bot.answer_callback_query(callback_query.id)
            return
        players_data['players'] = new_players_list
        await save_players(players_data)
        await bot.send_message(callback_query.from_user.id, f"✅ Игрок с ID {player_id} удалён!")
    except Exception as e:
        logger.exception("Ошибка при удалении игрока")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'cancel_remove')
async def cancel_remove(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Удаление отменено")
    await bot.send_message(callback_query.from_user.id, "❌ Удаление отменено")

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
        players_data = await load_players()
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
        await save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
    except ValueError:
        await message.reply("❌ ID должен быть числом!")
    except Exception as e:
        logger.exception("Ошибка при добавлении игрока")

@dp.message(Command(commands=['leaderboard']))
async def leaderboard(message: types.Message):
    players_data = await load_players()
    players = players_data['players']
    if not players:
        await message.reply("Список игроков пуст!")
        return
    sorted_players = sorted(players, key=lambda p: p['stats'].get('rank_points', 0), reverse=True)
    text = "*Лидерборд игроков:*\n\n"
    for i, p in enumerate(sorted_players, 1):
        text += f"• *{i}. {p['name']}* — *{p['stats'].get('rank_points', 0)}* очков\n"
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players_data = await load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (
            "*Ваша статистика:*\n\n"
            f"• *Звание:* {stats.get('rank', 'Рядовой')}\n"
            f"• *Очки:* {stats.get('rank_points', 0)}\n"
            f"• *Игр сыграно:* {stats.get('games_played', 0)}\n"
            f"• *MVP:* {awards.get('mvp', 0)} раз\n"
            f"• *1st:* {awards.get('place1', 0)} раз\n"
            f"• *2nd:* {awards.get('place2', 0)} раз\n"
            f"• *3rd:* {awards.get('place3', 0)} раз\n"
            f"• *Прорыв вечера:* {awards.get('breakthrough', 0)} раз\n"
        )
        await message.reply(response, parse_mode="Markdown")
    else:
        await message.reply("❌ Вы не в списке игроков!")

@dp.message(Command(commands=['start_game']))
async def start_game(message: types.Message):
    global current_voting_participants
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
        return
    args = message.text.split(maxsplit=1)[1:]
    if not args:
        await message.reply("ℹ️ Используй: /start_game [ID1 ID2 ...]")
        return
    try:
        player_ids = [int(x) for x in args[0].split()]
        players_data = await load_players()
        current_voting_participants = player_ids
        for p in players_data['players']:
            was_played = p['played_last_game']
            p['played_last_game'] = p['id'] in player_ids
            if p['played_last_game'] and not was_played:
                p['stats']['games_played'] += 1
        await save_players(players_data)
        participant_names = [p['name'] for p in players_data['players'] if p['id'] in player_ids]
        await message.reply(f"✅ Игра начата! Участники ({len(player_ids)}):\n" + "\n".join(participant_names))
        logger.info("Игра начата с участниками: %s", player_ids)
    except ValueError:
        await message.reply("❌ ID должны быть числами!")
    except Exception as e:
        logger.exception("Ошибка при запуске игры: %s", e)

@dp.message(Command(commands=['game_players']))
async def game_players(message: types.Message):
    players_data = await load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if not participants:
        await message.reply("❌ Нет участников последней игры!")
        return
    response = "*Участники последней игры:*\n\n" + "\n".join(
        f"• {p['name']} (ID: {p['id']})" for p in participants
    )
    await message.reply(response, parse_mode="Markdown")
    logger.info("Список участников запрошен пользователем %s", message.from_user.id)

@dp.callback_query(lambda c: c.data == 'start_voting_menu')
async def start_voting_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text="Начать голосование", callback_data="start_voting")],
        [types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_voting")],
        [types.InlineKeyboardButton(text="Начать 'Прорыв вечера'", callback_data="start_breakthrough")],
        [types.InlineKeyboardButton(text="Остановить 'Прорыв вечера'", callback_data="stop_breakthrough")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Управление голосованием:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'start_voting')
async def start_voting(callback_query: types.CallbackQuery):
    global voting_active, voting_message_id, voting_timer_message_id, auto_finish_task, current_voting_participants, voted_users
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование уже активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    players_data = await load_players()
    all_players = players_data['players']
    participants = [p for p in all_players if p['played_last_game']]
    if len(participants) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно участников для голосования (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']} (ID: {p['id']})", callback_data=f"exclude_{p['id']}")]
        for p in all_players
    ]
    inline_keyboard.append([types.InlineKeyboardButton(text="Подтвердить", callback_data="confirm_voting_start")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Кто НЕ участвовал в последней игре? (Выберите игроков для исключения):", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('exclude_'))
async def exclude_player(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = await load_players()
    for p in players_data['players']:
        if p['id'] == player_id:
            p['played_last_game'] = False
    await save_players(players_data)
    await bot.answer_callback_query(callback_query.id, f"Игрок {player_id} исключён из участников.")

@dp.callback_query(lambda c: c.data == 'confirm_voting_start')
async def confirm_voting_start(callback_query: types.CallbackQuery):
    global voting_active, voting_message_id, voting_timer_message_id, auto_finish_task, current_voting_participants, voted_users
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = await load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if len(participants) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно участников для голосования (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_active = True
    current_voting_participants = [p['id'] for p in participants]
    voted_users = []
    message = await bot.send_message(GROUP_ID, "🏆 Голосование за рейтинг началось! Участники, проверьте ЛС.")
    voting_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, voting_message_id, disable_notification=True)
    timer_message = await bot.send_message(GROUP_ID, "⏳ *Время до конца основного голосования:* Инициализация...")
    voting_timer_message_id = timer_message.message_id
    auto_finish_task = asyncio.create_task(auto_finish_voting())
    asyncio.create_task(update_timer(GROUP_ID, voting_timer_message_id, AUTO_FINISH_DELAY, "основное"))
    
    for participant in participants:
        inline_keyboard = [
            [types.InlineKeyboardButton(text="Завершить голосование", callback_data="finish_voting_user")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(participant['id'], "🏆 Началось голосование за рейтинг! Пока функционал голосования не полностью реализован, нажмите 'Завершить голосование'.", reply_markup=keyboard)
    
    await bot.send_message(callback_query.from_user.id, "✅ Голосование запущено!")
    await bot.answer_callback_query(callback_query.id)
    logger.info("Голосование запущено администратором %s", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data == 'stop_voting')
async def stop_voting(callback_query: types.CallbackQuery):
    global voting_active, voting_message_id, voting_timer_message_id, auto_finish_task
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование не активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_active = False
    if auto_finish_task:
        auto_finish_task.cancel()
        auto_finish_task = None
    if voting_message_id:
        await bot.unpin_chat_message(GROUP_ID, voting_message_id)
        await bot.send_message(GROUP_ID, "🏆 Голосование остановлено администратором!")
    if voting_timer_message_id:
        await bot.delete_message(GROUP_ID, voting_timer_message_id)
        voting_timer_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🏆 Голосование было остановлено администратором!")
        except Exception as e:
            logger.exception("Не удалось уведомить участника %s", participant_id)
    await bot.send_message(callback_query.from_user.id, "✅ Голосование остановлено!")
    await bot.answer_callback_query(callback_query.id)
    logger.info("Голосование остановлено администратором %s", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data.startswith('finish_voting_user'))
async def finish_voting_user(callback_query: types.CallbackQuery):
    global voting_active, auto_finish_task, voted_users
    user_id = callback_query.from_user.id
    if user_id not in current_voting_participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    if user_id in voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы уже завершили голосование!")
        return
    players_data = await load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    player['stats']['votes_cast'] = player['stats'].get('votes_cast', 0) + 1
    voted_users.append(user_id)
    await save_players(players_data)
    await bot.send_message(user_id, "✅ Ваше голосование завершено!")
    await bot.edit_message_reply_markup(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        reply_markup=None
    )
    await bot.answer_callback_query(callback_query.id)
    all_finished = len(voted_users) >= len(current_voting_participants)
    if all_finished and voting_active:
        if auto_finish_task is not None:
            auto_finish_task.cancel()
            auto_finish_task = None
        await check_voting_complete()

async def calculate_voting_results(players_data):
    participants = [p for p in players_data['players'] if p['played_last_game']]
    averages = {p['id']: get_average_rating(p) for p in participants}
    sorted_players = sorted(participants, key=lambda p: averages[p['id']], reverse=True)
    points_map = {1: 25, 2: 20, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 3, 10: 2}
    awards_notifications = []
    for i, player in enumerate(sorted_players[:10], 1):
        points = points_map[i]
        player['stats']['rank_points'] = player['stats'].get('rank_points', 0) + points
        if i == 1:
            player['awards']['mvp'] += 1
            player['stats']['mvp_count'] += 1
            awards_notifications.append((player['id'], f"🏆 Вы получили награду MVP (+{points} очков)!"))
        elif i == 2:
            player['awards']['place1'] += 1
            awards_notifications.append((player['id'], f"🥇 1-е место (+{points} очков)!"))
        elif i == 3:
            player['awards']['place2'] += 1
            awards_notifications.append((player['id'], f"🥈 2-е место (+{points} очков)!"))
        elif i == 4:
            player['awards']['place3'] += 1
            awards_notifications.append((player['id'], f"🥉 3-е место (+{points} очков)!"))
        else:
            awards_notifications.append((player['id'], f"Топ-{i} (+{points} очков)!"))
        update_rank(player)
    return sorted_players, averages, awards_notifications

async def notify_voting_winners(awards_notifications):
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", winner_id)

async def publish_voting_results(sorted_players, averages):
    result = "🏆 *Голосование за рейтинг завершено!*\n\n*Результаты боя:*\n"
    for i, p in enumerate(sorted_players[:10], 1):
        result += f"{i}. {p['name']} — {averages[p['id']]:.2f}"
        if i == 1:
            result += " (MVP 🏆)"
        elif i == 2:
            result += " (🥇 1st)"
        elif i == 3:
            result += " (🥈 2nd)"
        elif i == 4:
            result += " (🥉 3rd)"
        result += "\n"
    message = await bot.send_message(GROUP_ID, result, parse_mode="Markdown")
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    return message.message_id

async def check_voting_complete():
    global voting_active, breakthrough_voting_active, voting_message_id, voting_timer_message_id, voted_users
    players_data = await load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if not participants:
        return False
    sorted_players, averages, awards_notifications = await calculate_voting_results(players_data)
    for p in players_data['players']:
        p['ratings'] = []
    await save_players(players_data)
    new_message_id = await publish_voting_results(sorted_players, averages)
    if voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_message_id)
    if voting_timer_message_id:
        await bot.delete_message(chat_id=GROUP_ID, message_id=voting_timer_message_id)
        voting_timer_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🏆 Голосование завершено! Проверьте результаты в группе!")
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", participant_id)
    await notify_voting_winners(awards_notifications)
    await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено! Запускаем 'Прорыв вечера'.")
    voting_active = False
    voted_users.clear()
    breakthrough_voting_active = True
    await start_breakthrough_voting()
    logger.info("Основное голосование завершено")
    return True

@dp.callback_query(lambda c: c.data == 'start_breakthrough')
async def start_breakthrough(callback_query: types.CallbackQuery):
    global breakthrough_voting_active, breakthrough_message_id, breakthrough_timer_message_id, voted_breakthrough_users
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if breakthrough_voting_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование за 'Прорыв вечера' уже активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    await start_breakthrough_voting()
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' запущено!")
    await bot.answer_callback_query(callback_query.id)

async def start_breakthrough_voting():
    global breakthrough_voting_active, breakthrough_message_id, breakthrough_timer_message_id, voted_breakthrough_users
    players_data = await load_players()
    eligible_players = [p for p in players_data['players'] if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.send_message(GROUP_ID, "🚀 Нет кандидатов на 'Прорыв вечера'.")
        return
    breakthrough_voting_active = True
    voted_breakthrough_users = []
    message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' началось! Участники, проверьте ЛС.")
    breakthrough_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, breakthrough_message_id, disable_notification=True)
    timer_message = await bot.send_message(GROUP_ID, "⏳ *Время до конца голосования за Прорыв вечера:* Инициализация...")
    breakthrough_timer_message_id = timer_message.message_id
    asyncio.create_task(update_timer(GROUP_ID, breakthrough_timer_message_id, AUTO_FINISH_DELAY, "Прорыв вечера"))
    
    participants = [p for p in players_data['players'] if p['played_last_game']]
    for participant in participants:
        inline_keyboard = [
            [types.InlineKeyboardButton(text=f"{p['name']}", callback_data=f"breakthrough_{p['id']}")] for p in eligible_players
        ]
        inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(participant['id'], "🚀 Выберите игрока для 'Прорыва вечера':", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == 'stop_breakthrough')
async def stop_breakthrough(callback_query: types.CallbackQuery):
    global breakthrough_voting_active, breakthrough_message_id, breakthrough_timer_message_id
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not breakthrough_voting_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование за 'Прорыв вечера' не активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    breakthrough_voting_active = False
    if breakthrough_message_id:
        await bot.unpin_chat_message(GROUP_ID, breakthrough_message_id)
        await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' остановлено администратором!")
    if breakthrough_timer_message_id:
        await bot.delete_message(GROUP_ID, breakthrough_timer_message_id)
        breakthrough_timer_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' было остановлено администратором!")
        except Exception as e:
            logger.exception("Не удалось уведомить участника %s", participant_id)
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' остановлено!")
    await bot.answer_callback_query(callback_query.id)
    logger.info("Голосование за 'Прорыв вечера' остановлено администратором %s", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data.startswith('breakthrough_'))
async def process_breakthrough_rating(callback_query: types.CallbackQuery):
    global breakthrough_voting_active, voted_breakthrough_users
    user_id = callback_query.from_user.id
    if user_id not in current_voting_participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    if user_id in voted_breakthrough_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы уже проголосовали за 'Прорыв вечера'!")
        return
    data = callback_query.data.split('_')
    player_id = int(data[1])
    players_data = await load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            if 'breakthrough_ratings' not in player:
                player['breakthrough_ratings'] = []
            player['breakthrough_ratings'].append(1)
            voted_breakthrough_users.append(user_id)
            await save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Вы проголосовали за {player['name']} как 'Прорыв вечера'!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_breakthrough_voting_complete():
        logger.info("Голосование за 'Прорыв вечера' автоматически завершено")

async def check_breakthrough_voting_complete():
    global breakthrough_voting_active, breakthrough_message_id, breakthrough_timer_message_id, voted_breakthrough_users
    players_data = await load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    eligible_players = [p for p in players_data['players'] if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        breakthrough_voting_active = False
        message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' завершено!\n\nНет кандидатов.")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
        if breakthrough_message_id:
            await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=breakthrough_message_id)
        if breakthrough_timer_message_id:
            await bot.delete_message(chat_id=GROUP_ID, message_id=breakthrough_timer_message_id)
            breakthrough_timer_message_id = None
        return True
    total_participants = len(participants)
    if len(voted_breakthrough_users) < total_participants:
        return False
    sorted_eligible = sorted(eligible_players, key=lambda p: len(p.get('breakthrough_ratings', [])), reverse=True)
    max_votes = len(sorted_eligible[0].get('breakthrough_ratings', [])) if sorted_eligible else 0
    winners = [p for p in sorted_eligible if len(p.get('breakthrough_ratings', [])) == max_votes]
    awards_notifications = []
    if winners:
        winner_names = ", ".join(p['name'] for p in winners)
        for winner in winners:
            winner['awards']['breakthrough'] = winner['awards'].get('breakthrough', 0) + 1
            winner['stats']['rank_points'] = winner['stats'].get('rank_points', 0) + 10
            update_rank(winner)
            awards_notifications.append((winner['id'], f"🚀 Вы получили награду 'Прорыв вечера' (+10 очков)!"))
        result = f"🚀 *Голосование за 'Прорыв вечера' завершено!*\n\n*Прорыв вечера:* {winner_names}!"
        message = await bot.send_message(GROUP_ID, result, parse_mode="Markdown")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    for player in players_data['players']:
        player.pop('breakthrough_ratings', None)
    await save_players(players_data)
    if breakthrough_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=breakthrough_message_id)
    if breakthrough_timer_message_id:
        await bot.delete_message(chat_id=GROUP_ID, message_id=breakthrough_timer_message_id)
        breakthrough_timer_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' завершено! Проверьте результаты в группе!")
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", participant_id)
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", winner_id)
    breakthrough_voting_active = False
    voted_breakthrough_users.clear()
    logger.info("Голосование за 'Прорыв вечера' завершено")
    return True

@dp.callback_query()
async def default_callback_handler(callback_query: types.CallbackQuery):
    logger.info("Необработанный callback: %s от пользователя %s", callback_query.data, callback_query.from_user.id)
    await bot.answer_callback_query(callback_query.id, "Команда не распознана!")

# --- Настройка вебхука и запуск приложения ---

async def health_check(request):
    return web.Response(text="OK", status=200)

async def on_startup(dispatcher: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL)
    webhook_info = await bot.get_webhook_info()
    logger.info("Webhook info: %s", webhook_info)
    if webhook_info.url != WEBHOOK_URL:
        logger.error("Webhook не установлен корректно!")
    else:
        logger.info("Бот запущен с вебхуком: %s", WEBHOOK_URL)

async def on_shutdown(dispatcher: Dispatcher):
    await bot.delete_webhook()
    logger.info("Бот остановлен")

async def main():
    app = web.Application()
    webhook_request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_request_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get('/', health_check)  # Health check для Render
    setup_application(app, dp, bot=bot)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Сервер запущен на порту %s", port)
    
    try:
        await asyncio.Event().wait()  # Держим сервер запущенным
    except asyncio.CancelledError:
        logger.info("Сервер остановлен")
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")
    except Exception as e:
        logger.exception("Ошибка при запуске приложения: %s", e)
