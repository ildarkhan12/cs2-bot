import os
import json
import asyncio
import logging
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Константы
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'
ADMIN_ID = 113405030
GROUP_ID = -1002484381098
BOT_USERNAME = "CS2_Team_Bot"
AUTO_FINISH_DELAY = 86400  # 24 часа в секундах

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Класс для управления состоянием голосования
class VotingState:
    def __init__(self):
        self.active = False
        self.breakthrough_active = False
        self.participants: List[int] = []
        self.voting_message_id: Optional[int] = None
        self.breakthrough_message_id: Optional[int] = None
        self.voting_timer_message_id: Optional[int] = None
        self.breakthrough_timer_message_id: Optional[int] = None
        self.voted_users: List[int] = []
        self.voted_breakthrough_users: List[int] = []
        self.auto_finish_task: Optional[asyncio.Task] = None

voting_state = VotingState()

# --- Работа с данными игроков ---

def load_players() -> Dict[str, List[Dict]]:
    """Загружает данные игроков из файла players.json."""
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return migrate_players_data(data)
    except FileNotFoundError:
        logger.warning("Файл players.json не найден, инициализируется пустой список")
        return {"players": []}
    except json.JSONDecodeError as e:
        logger.error("Ошибка парсинга players.json: %s", e)
        return {"players": []}
    except Exception as e:
        logger.exception("Ошибка загрузки players.json: %s", e)
        return {"players": []}

def save_players(data: Dict[str, List[Dict]]) -> None:
    """Сохраняет данные игроков в файл players.json."""
    try:
        with open('players.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.exception("Ошибка сохранения players.json: %s", e)

def migrate_players_data(data: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    """Миграция структуры данных игроков для обратной совместимости."""
    for player in data['players']:
        player.setdefault('stats', {})
        player.setdefault('awards', {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0})
        if 'avg_rating' in player['stats']:
            del player['stats']['avg_rating']
        player['stats'].setdefault('mvp_count', player['awards'].get('mvp', 0))
        player['stats'].setdefault('games_played', 0)
        player['stats'].setdefault('votes_cast', 0)
        if 'rank_points' not in player['stats']:
            points = (player['stats']['games_played'] * 5 +
                      player['awards'].get('mvp', 0) * 25 +
                      player['awards'].get('place1', 0) * 20 +
                      player['awards'].get('place2', 0) * 15 +
                      player['awards'].get('place3', 0) * 12 +
                      player['awards'].get('breakthrough', 0) * 10)
            player['stats']['rank_points'] = points
        update_rank(player)
        player['awards'].setdefault('breakthrough', 0)
    return data

def update_rank(player: Dict) -> None:
    """Обновляет звание игрока на основе очков."""
    points = player['stats'].get('rank_points', 0)
    ranks = [
        (801, "Майор"), (501, "Капитан"), (301, "Лейтенант"),
        (151, "Сержант"), (51, "Капрал"), (0, "Рядовой")
    ]
    for threshold, rank in ranks:
        if points >= threshold:
            player['stats']['rank'] = rank
            break

# --- Утилиты голосования ---

async def auto_finish_voting():
    """Автоматически завершает голосование через 24 часа."""
    await asyncio.sleep(AUTO_FINISH_DELAY)
    if voting_state.active:
        for participant_id in voting_state.participants:
            await bot.send_message(participant_id, "⏰ Голосование завершено автоматически через 24 часа.")
        await check_voting_complete()
        logger.info("Голосование завершено по таймеру")

async def update_timer(chat_id: int, message_id: int, duration: int, voting_type: str = "основное"):
    """Обновляет таймер голосования в чате."""
    start_time = asyncio.get_event_loop().time()
    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        remaining = max(0, duration - int(elapsed))
        minutes, seconds = divmod(remaining, 60)
        hours, minutes = divmod(minutes, 60)
        timer_text = f"⏳ *Время до конца {voting_type} голосования:*\n{hours:02d}:{minutes:02d}:{seconds:02d}"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=timer_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Не удалось обновить таймер: %s", e)
            break
        if remaining <= 0:
            if voting_type == "основное" and voting_state.active:
                await check_voting_complete()
            elif voting_type == "Прорыв вечера" and voting_state.breakthrough_active:
                await check_breakthrough_voting_complete()
            break
        await asyncio.sleep(300)  # Обновление каждые 5 минут

# --- Общие функции для меню ---

def build_main_menu(user_id: int) -> types.InlineKeyboardMarkup:
    """Создаёт главное меню с учётом прав администратора."""
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Список команд", callback_data="help"),
            types.InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")
        ]
    ]
    if user_id == ADMIN_ID:
        inline_keyboard.extend([
            [
                types.InlineKeyboardButton(text="Управление игроками", callback_data="manage_players"),
                types.InlineKeyboardButton(text="Голосование", callback_data="start_voting_menu")
            ],
            [types.InlineKeyboardButton(text="Список игроков", callback_data="list_players")]
        ])
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
    return types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

# --- Команды и обработчики ---

@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    if message.chat.type != "private":
        group_greeting = "Салам, боец!\nЯ бот вашей CS2-тусовки.\nℹ️ Пошли в ЛС для управления:"
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Перейти в ЛС", url=f"t.me/{BOT_USERNAME}")]
        ])
        await message.reply(group_greeting, reply_markup=keyboard)
        return
    welcome_text = "Салам, боец!\nЯ бот вашей CS2-тусовки. Выбери действие:"
    keyboard = build_main_menu(message.from_user.id)
    await message.reply(welcome_text, reply_markup=keyboard)
    logger.info("Отправлено приветственное сообщение пользователю %s", message.from_user.id)

@dp.callback_query(lambda c: c.data == 'start')
async def start_callback(callback_query: types.CallbackQuery):
    welcome_text = "Салам, боец!\nЯ бот вашей CS2-тусовки. Выбери действие:"
    keyboard = build_main_menu(callback_query.from_user.id)
    try:
        await bot.edit_message_text(
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
            text=welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception:
        await bot.send_message(callback_query.from_user.id, welcome_text, reply_markup=keyboard, parse_mode="Markdown")
    await bot.answer_callback_query(callback_query.id)

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
    user_id = callback_query.from_user.id
    players_data = load_players()
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
    else:
        response = "❌ Вы не в списке игроков!"
    await bot.send_message(user_id, response, parse_mode="Markdown")
    await bot.answer_callback_query(callback_query.id)
    logger.debug("Статистика отправлена пользователю %s", user_id)

@dp.callback_query(lambda c: c.data == 'list_players')
async def list_players_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = load_players()
    players = players_data['players']
    if not players:
        response = "❌ Список игроков пуст!"
    else:
        response = "*Список игроков:*\n\n"
        for i, player in enumerate(players, 1):
            response += (
                f"{i}. *{player['name']}* (ID: {player['id']})\n"
                f"   Звание: {player['stats'].get('rank', 'Рядовой')}, "
                f"Очки: {player['stats'].get('rank_points', 0)}\n"
            )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
    ])
    await bot.send_message(callback_query.from_user.id, response, parse_mode="Markdown", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

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
    await bot.send_message(callback_query.from_user.id, "Используйте команду /add_player [ID] [Имя]")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'remove_player_prompt')
async def remove_player_prompt(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = load_players()
    if not players_data['players']:
        await bot.send_message(callback_query.from_user.id, "❌ Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']} (ID: {p['id']})", callback_data=f"confirm_remove_{p['id']}")]
        for p in players_data['players']
    ]
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_players")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выберите игрока для удаления:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
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
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

@dp.message(Command(commands=['remove_player']))
async def remove_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
        return
    args = message.text.split(maxsplit=1)[1:]
    if not args:
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
    player_id = int(callback_query.data.split('_')[2])
    players_data = load_players()
    initial_len = len(players_data['players'])
    players_data['players'] = [p for p in players_data['players'] if p['id'] != player_id]
    if len(players_data['players']) == initial_len:
        await bot.send_message(callback_query.from_user.id, f"❌ Игрок с ID {player_id} не найден!")
    else:
        save_players(players_data)
        await bot.send_message(callback_query.from_user.id, f"✅ Игрок с ID {player_id} удалён!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'cancel_remove')
async def cancel_remove(callback_query: types.CallbackQuery):
    await bot.send_message(callback_query.from_user.id, "❌ Удаление отменено")
    await bot.answer_callback_query(callback_query.id)

@dp.message(Command(commands=['leaderboard']))
async def leaderboard(message: types.Message):
    players_data = load_players()
    if not players_data['players']:
        await message.reply("Список игроков пуст!")
        return
    sorted_players = sorted(players_data['players'], key=lambda p: p['stats'].get('rank_points', 0), reverse=True)
    text = "*Лидерборд игроков:*\n\n"
    text += "\n".join(f"• *{i}. {p['name']}* — *{p['stats'].get('rank_points', 0)}* очков" for i, p in enumerate(sorted_players, 1))
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players_data = load_players()
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
    else:
        response = "❌ Вы не в списке игроков!"
    await message.reply(response, parse_mode="Markdown")

@dp.message(Command(commands=['start_game']))
async def start_game(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
        return
    args = message.text.split(maxsplit=1)[1:]
    if not args:
        await message.reply("ℹ️ Используй: /start_game [ID1 ID2 ...]")
        return
    try:
        player_ids = [int(x) for x in args[0].split()]
        players_data = load_players()
        voting_state.participants = player_ids
        for p in players_data['players']:
            was_played = p['played_last_game']
            p['played_last_game'] = p['id'] in player_ids
            if p['played_last_game'] and not was_played:
                p['stats']['games_played'] += 1
        save_players(players_data)
        participant_names = [p['name'] for p in players_data['players'] if p['id'] in player_ids]
        await message.reply(f"✅ Игра начата! Участники ({len(player_ids)}):\n" + "\n".join(participant_names))
    except ValueError:
        await message.reply("❌ ID должны быть числами!")

@dp.message(Command(commands=['game_players']))
async def game_players(message: types.Message):
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if not participants:
        await message.reply("❌ Нет участников последней игры!")
        return
    response = "*Участники последней игры:*\n\n" + "\n".join(f"• {p['name']} (ID: {p['id']})" for p in participants)
    await message.reply(response, parse_mode="Markdown")

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
    await bot.send_message(callback_query.from_user.id, "Управление голосованием:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'start_voting')
async def start_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_state.active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование уже активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if len(participants) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно участников для голосования (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']} (ID: {p['id']})", callback_data=f"exclude_{p['id']}")]
        for p in players_data['players']
    ]
    inline_keyboard.append([types.InlineKeyboardButton(text="Подтвердить", callback_data="confirm_voting_start")])
    await bot.send_message(callback_query.from_user.id, "Кто НЕ участвовал в последней игре? (Выберите игроков для исключения):",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('exclude_'))
async def exclude_player(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    for p in players_data['players']:
        if p['id'] == player_id:
            p['played_last_game'] = False
    save_players(players_data)
    await bot.answer_callback_query(callback_query.id, f"Игрок {player_id} исключён из участников.")

@dp.callback_query(lambda c: c.data == 'confirm_voting_start')
async def confirm_voting_start(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if len(participants) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно участников для голосования (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.active = True
    voting_state.participants = [p['id'] for p in participants]
    voting_state.voted_users.clear()
    message = await bot.send_message(GROUP_ID, "🏆 Голосование за рейтинг началось! Участники, проверьте ЛС.")
    voting_state.voting_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, voting_state.voting_message_id, disable_notification=True)
    timer_message = await bot.send_message(GROUP_ID, "⏳ *Время до конца основного голосования:* Инициализация...")
    voting_state.voting_timer_message_id = timer_message.message_id
    voting_state.auto_finish_task = asyncio.create_task(auto_finish_voting())
    asyncio.create_task(update_timer(GROUP_ID, voting_state.voting_timer_message_id, AUTO_FINISH_DELAY, "основное"))
    for participant in participants:
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Завершить голосование", callback_data="finish_voting_user")]
        ])
        await bot.send_message(participant['id'], "🏆 Началось голосование за рейтинг! Нажмите 'Завершить голосование'.", reply_markup=keyboard)
    await bot.send_message(callback_query.from_user.id, "✅ Голосование запущено!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'stop_voting')
async def stop_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование не активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.active = False
    if voting_state.auto_finish_task:
        voting_state.auto_finish_task.cancel()
        voting_state.auto_finish_task = None
    if voting_state.voting_message_id:
        await bot.unpin_chat_message(GROUP_ID, voting_state.voting_message_id)
        await bot.send_message(GROUP_ID, "🏆 Голосование остановлено администратором!")
    if voting_state.voting_timer_message_id:
        await bot.delete_message(GROUP_ID, voting_state.voting_timer_message_id)
        voting_state.voting_timer_message_id = None
    for participant_id in voting_state.participants:
        await bot.send_message(participant_id, "🏆 Голосование было остановлено администратором!")
    await bot.send_message(callback_query.from_user.id, "✅ Голосование остановлено!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'finish_voting_user')
async def finish_voting_user(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    if user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы уже завершили голосование!")
        return
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    player['stats']['votes_cast'] += 1
    voting_state.voted_users.append(user_id)
    save_players(players_data)
    await bot.send_message(user_id, "✅ Ваше голосование завершено!")
    await bot.edit_message_reply_markup(chat_id=user_id, message_id=callback_query.message.message_id, reply_markup=None)
    await bot.answer_callback_query(callback_query.id)
    if len(voting_state.voted_users) >= len(voting_state.participants) and voting_state.active:
        if voting_state.auto_finish_task:
            voting_state.auto_finish_task.cancel()
        await check_voting_complete()

async def calculate_voting_results(players_data: Dict) -> tuple:
    participants = [p for p in players_data['players'] if p['played_last_game']]
    # Здесь пока нет полной реализации рейтинга, поэтому просто распределяем награды
    sorted_players = participants  # Заменить на реальную сортировку по рейтингам
    points_map = {1: 25, 2: 20, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 3, 10: 2}
    awards_notifications = []
    for i, player in enumerate(sorted_players[:10], 1):
        points = points_map.get(i, 0)
        player['stats']['rank_points'] += points
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
    return sorted_players, {}, awards_notifications  # Второй аргумент - заглушка для averages

async def publish_voting_results(sorted_players: List[Dict], averages: Dict) -> int:
    result = "🏆 *Голосование за рейтинг завершено!*\n\n*Результаты боя:*\n"
    for i, p in enumerate(sorted_players[:10], 1):
        result += f"{i}. {p['name']}"
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
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if not participants:
        return
    sorted_players, averages, awards_notifications = await calculate_voting_results(players_data)
    for p in players_data['players']:
        p['ratings'] = []
    save_players(players_data)
    new_message_id = await publish_voting_results(sorted_players, averages)
    if voting_state.voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.voting_message_id)
    if voting_state.voting_timer_message_id:
        await bot.delete_message(chat_id=GROUP_ID, message_id=voting_state.voting_timer_message_id)
        voting_state.voting_timer_message_id = None
    for participant_id in voting_state.participants:
        await bot.send_message(participant_id, "🏆 Голосование завершено! Проверьте результаты в группе!")
    for winner_id, award_text in awards_notifications:
        await bot.send_message(winner_id, award_text)
    await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено! Запускаем 'Прорыв вечера'.")
    voting_state.active = False
    voting_state.voted_users.clear()
    voting_state.breakthrough_active = True
    await start_breakthrough_voting()

@dp.callback_query(lambda c: c.data == 'start_breakthrough')
async def start_breakthrough(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_state.breakthrough_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование за 'Прорыв вечера' уже активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    await start_breakthrough_voting()
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' запущено!")
    await bot.answer_callback_query(callback_query.id)

async def start_breakthrough_voting():
    players_data = load_players()
    eligible_players = [p for p in players_data['players'] if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.send_message(GROUP_ID, "🚀 Нет кандидатов на 'Прорыв вечера'.")
        return
    voting_state.breakthrough_active = True
    voting_state.voted_breakthrough_users.clear()
    message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' началось! Участники, проверьте ЛС.")
    voting_state.breakthrough_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, voting_state.breakthrough_message_id, disable_notification=True)
    timer_message = await bot.send_message(GROUP_ID, "⏳ *Время до конца голосования за Прорыв вечера:* Инициализация...")
    voting_state.breakthrough_timer_message_id = timer_message.message_id
    asyncio.create_task(update_timer(GROUP_ID, voting_state.breakthrough_timer_message_id, AUTO_FINISH_DELAY, "Прорыв вечера"))
    participants = [p for p in players_data['players'] if p['played_last_game']]
    for participant in participants:
        inline_keyboard = [
            [types.InlineKeyboardButton(text=f"{p['name']}", callback_data=f"breakthrough_{p['id']}")] for p in eligible_players
        ]
        inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
        await bot.send_message(participant['id'], "🚀 Выберите игрока для 'Прорыва вечера':",
                              reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))

@dp.callback_query(lambda c: c.data == 'stop_breakthrough')
async def stop_breakthrough(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.breakthrough_active:
        await bot.send_message(callback_query.from_user.id, "❌ Голосование за 'Прорыв вечера' не активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.breakthrough_active = False
    if voting_state.breakthrough_message_id:
        await bot.unpin_chat_message(GROUP_ID, voting_state.breakthrough_message_id)
        await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' остановлено администратором!")
    if voting_state.breakthrough_timer_message_id:
        await bot.delete_message(GROUP_ID, voting_state.breakthrough_timer_message_id)
        voting_state.breakthrough_timer_message_id = None
    for participant_id in voting_state.participants:
        await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' было остановлено администратором!")
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' остановлено!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('breakthrough_'))
async def process_breakthrough_rating(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    if user_id in voting_state.voted_breakthrough_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы уже проголосовали за 'Прорыв вечера'!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player.setdefault('breakthrough_ratings', []).append(1)
            voting_state.voted_breakthrough_users.append(user_id)
            save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Вы проголосовали за {player['name']} как 'Прорыв вечера'!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_breakthrough_voting_complete():
        logger.info("Голосование за 'Прорыв вечера' завершено")

async def check_breakthrough_voting_complete():
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    eligible_players = [p for p in players_data['players'] if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        voting_state.breakthrough_active = False
        message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' завершено!\n\nНет кандидатов.")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
        if voting_state.breakthrough_message_id:
            await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_message_id)
        if voting_state.breakthrough_timer_message_id:
            await bot.delete_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_timer_message_id)
            voting_state.breakthrough_timer_message_id = None
        return True
    if len(voting_state.voted_breakthrough_users) < len(participants):
        return False
    sorted_eligible = sorted(eligible_players, key=lambda p: len(p.get('breakthrough_ratings', [])), reverse=True)
    max_votes = len(sorted_eligible[0].get('breakthrough_ratings', [])) if sorted_eligible else 0
    winners = [p for p in sorted_eligible if len(p.get('breakthrough_ratings', [])) == max_votes]
    if winners:
        winner_names = ", ".join(p['name'] for p in winners)
        for winner in winners:
            winner['awards']['breakthrough'] += 1
            winner['stats']['rank_points'] += 10
            update_rank(winner)
            await bot.send_message(winner['id'], "🚀 Вы получили награду 'Прорыв вечера' (+10 очков)!")
        result = f"🚀 *Голосование за 'Прорыв вечера' завершено!*\n\n*Прорыв вечера:* {winner_names}!"
        message = await bot.send_message(GROUP_ID, result, parse_mode="Markdown")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    for player in players_data['players']:
        player.pop('breakthrough_ratings', None)
    save_players(players_data)
    if voting_state.breakthrough_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_message_id)
    if voting_state.breakthrough_timer_message_id:
        await bot.delete_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_timer_message_id)
        voting_state.breakthrough_timer_message_id = None
    for participant_id in voting_state.participants:
        await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' завершено! Проверьте результаты в группе!")
    voting_state.breakthrough_active = False
    voting_state.voted_breakthrough_users.clear()
    return True

@dp.callback_query()
async def default_callback_handler(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Команда не распознана!")

# --- Настройка вебхука и запуск ---

async def health_check(request):
    return web.Response(text="OK", status=200)

async def on_startup(_):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Бот запущен с вебхуком: %s", WEBHOOK_URL)

async def on_shutdown(_):
    await bot.delete_webhook()
    logger.info("Бот остановлен")

async def main():
    app = web.Application()
    webhook_request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_request_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get('/', health_check)
    setup_application(app, dp, bot=bot)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Сервер запущен на порту %s", port)
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
