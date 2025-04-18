import os
import json
import asyncio
import logging
import base64
import requests
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'
ADMIN_ID = 113405030
GROUP_ID = -1002484381098
BOT_USERNAME = "CS2_Team_Bot"
GIT_USERNAME = os.getenv('GIT_USERNAME', 'ildarkhan12')
GIT_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_NAME = 'cs2-bot'
GITHUB_API_URL_PLAYERS = f'https://api.github.com/repos/{GIT_USERNAME}/{REPO_NAME}/contents/players.json'
GITHUB_API_URL_STATE = f'https://api.github.com/repos/{GIT_USERNAME}/{REPO_NAME}/contents/voting_state.json'
STATE_FILE = 'voting_state.json'

bot = Bot(token=TOKEN)
dp = Dispatcher()
players_data_cache: Dict[str, List[Dict]] = None

class VotingState:
    def __init__(self):
        self.active = False
        self.breakthrough_active = False
        self.participants: List[int] = []
        self.excluded_players: List[int] = []
        self.voting_message_id: Optional[int] = None
        self.breakthrough_message_id: Optional[int] = None
        self.voted_users: List[int] = []
        self.breakthrough_voted_users: List[int] = []
        self.voting_messages: Dict[int, List[int]] = {}
        self.restart_notified = False

    def to_dict(self):
        return {
            'active': self.active,
            'breakthrough_active': self.breakthrough_active,
            'participants': self.participants,
            'excluded_players': self.excluded_players,
            'voting_message_id': self.voting_message_id,
            'breakthrough_message_id': self.breakthrough_message_id,
            'voted_users': self.voted_users,
            'breakthrough_voted_users': self.breakthrough_voted_users,
            'voting_messages': self.voting_messages,
            'restart_notified': self.restart_notified
        }

    @classmethod
    def from_dict(cls, data: Dict):
        state = cls()
        state.active = data.get('active', False)
        state.breakthrough_active = data.get('breakthrough_active', False)
        state.participants = data.get('participants', [])
        state.excluded_players = data.get('excluded_players', [])
        state.voting_message_id = data.get('voting_message_id')
        state.breakthrough_message_id = data.get('breakthrough_message_id')
        state.voted_users = data.get('voted_users', [])
        state.breakthrough_voted_users = data.get('breakthrough_voted_users', [])
        state.voting_messages = data.get('voting_messages', {})
        state.restart_notified = data.get('restart_notified', False)
        return state

voting_state = VotingState()

def load_players() -> Dict[str, List[Dict]]:
    global players_data_cache
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            players_data_cache = data
            return data
    except FileNotFoundError:
        logger.warning("players.json не найден локально")
        return asyncio.run(fetch_players_from_github())
    except Exception as e:
        logger.error("Ошибка загрузки players.json: %s", e)
        return {"players": []}

def save_players(data: Dict[str, List[Dict]]) -> None:
    global players_data_cache
    try:
        with open('players.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        players_data_cache = data
        asyncio.create_task(save_players_to_github(data))
    except Exception as e:
        logger.error("Ошибка сохранения players.json: %s", e)

async def fetch_players_from_github() -> Dict[str, List[Dict]]:
    headers = {'Authorization': f'token {GIT_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        response = requests.get(GITHUB_API_URL_PLAYERS, headers=headers)
        if response.status_code == 200:
            content = base64.b64decode(response.json()['content']).decode('utf-8')
            data = json.loads(content)
            save_players(data)
            return data
        elif response.status_code == 404:
            default_data = {"players": []}
            save_players(default_data)
            return default_data
    except Exception as e:
        logger.error("Ошибка загрузки players.json из GitHub: %s", e)
        return {"players": []}

async def save_players_to_github(data: Dict[str, List[Dict]]) -> None:
    headers = {'Authorization': f'token {GIT_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        response = requests.get(GITHUB_API_URL_PLAYERS, headers=headers)
        sha = response.json().get('sha') if response.status_code == 200 else None
        content = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=4).encode('utf-8')).decode('utf-8')
        payload = {'message': 'Update players.json', 'content': content, 'branch': 'main'}
        if sha:
            payload['sha'] = sha
        response = requests.put(GITHUB_API_URL_PLAYERS, headers=headers, json=payload)
        if response.status_code not in [200, 201]:
            logger.error("Ошибка сохранения players.json в GitHub: %s", response.text)
    except Exception as e:
        logger.error("Ошибка при сохранении players.json в GitHub: %s", e)

def load_voting_state() -> VotingState:
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return VotingState.from_dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return asyncio.run(fetch_voting_state_from_github())

def save_voting_state(state: VotingState) -> None:
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=4)
        asyncio.create_task(save_voting_state_to_github(state))
    except Exception as e:
        logger.error("Ошибка сохранения voting_state.json: %s", e)

async def fetch_voting_state_from_github() -> VotingState:
    headers = {'Authorization': f'token {GIT_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        response = requests.get(GITHUB_API_URL_STATE, headers=headers)
        if response.status_code == 200:
            content = base64.b64decode(response.json()['content']).decode('utf-8')
            data = json.loads(content)
            save_voting_state(VotingState.from_dict(data))
            return VotingState.from_dict(data)
        elif response.status_code == 404:
            default_state = VotingState()
            save_voting_state(default_state)
            return default_state
    except Exception as e:
        logger.error("Ошибка загрузки voting_state.json из GitHub: %s", e)
        return VotingState()

async def save_voting_state_to_github(state: VotingState) -> None:
    headers = {'Authorization': f'token {GIT_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        response = requests.get(GITHUB_API_URL_STATE, headers=headers)
        sha = response.json().get('sha') if response.status_code == 200 else None
        content = base64.b64encode(json.dumps(state.to_dict(), ensure_ascii=False, indent=4).encode('utf-8')).decode('utf-8')
        payload = {'message': 'Update voting_state.json', 'content': content, 'branch': 'main'}
        if sha:
            payload['sha'] = sha
        response = requests.put(GITHUB_API_URL_STATE, headers=headers, json=payload)
        if response.status_code not in [200, 201]:
            logger.error("Ошибка сохранения voting_state.json в GitHub: %s", response.text)
    except Exception as e:
        logger.error("Ошибка при сохранении voting_state.json в GitHub: %s", e)

def update_rank(player: Dict) -> None:
    points = player['stats'].get('rank_points', 0)
    ranks = [(801, "Майор"), (501, "Капитан"), (301, "Лейтенант"), (151, "Сержант"), (51, "Капрал"), (0, "Рядовой")]
    for threshold, rank in ranks:
        if points >= threshold:
            player['stats']['rank'] = rank
            break

def build_main_menu(user_id: int) -> types.InlineKeyboardMarkup:
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Список команд", callback_data="help"),
            types.InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")
        ]
    ]
    players_data = load_players()
    user_participated = any(p['id'] == user_id and p['played_last_game'] for p in players_data['players'])
    if (voting_state.active or voting_state.breakthrough_active) and user_participated:
        inline_keyboard.append([types.InlineKeyboardButton(text="Голосование", callback_data="user_voting_menu")])
    if user_id == ADMIN_ID:
        inline_keyboard.extend([
            [
                types.InlineKeyboardButton(text="Управление игроками", callback_data="manage_players"),
                types.InlineKeyboardButton(text="Голосование (админ)", callback_data="start_voting_menu")
            ],
            [types.InlineKeyboardButton(text="Список игроков", callback_data="list_players")]
        ])
    return types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def build_voting_menu() -> types.InlineKeyboardMarkup:
    inline_keyboard = []
    players_data = load_players()
    has_last_game = any(p['played_last_game'] for p in players_data['players'])
    if voting_state.active:
        inline_keyboard.extend([
            [types.InlineKeyboardButton(text="Голосование за рейтинг (в процессе)", callback_data="voting_in_progress")],
            [types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_voting")],
            [types.InlineKeyboardButton(text="Промежуточные результаты", callback_data="voting_results")],
            [types.InlineKeyboardButton(text="Напомнить отстающим", callback_data="remind_laggards")]
        ])
    elif voting_state.breakthrough_active:
        inline_keyboard.extend([
            [types.InlineKeyboardButton(text="Прорыв вечера (в процессе)", callback_data="breakthrough_in_progress")],
            [types.InlineKeyboardButton(text="Остановить 'Прорыв вечера'", callback_data="stop_breakthrough")],
            [types.InlineKeyboardButton(text="Промежуточные результаты", callback_data="breakthrough_results")],
            [types.InlineKeyboardButton(text="Напомнить отстающим", callback_data="remind_laggards")]
        ])
    elif has_last_game:
        inline_keyboard.append([types.InlineKeyboardButton(text="Начать 'Прорыв вечера'", callback_data="start_breakthrough")])
    else:
        inline_keyboard.append([types.InlineKeyboardButton(text="Начать голосование за рейтинг", callback_data="start_voting")])
    inline_keyboard.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")])
    return types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    if message.chat.type != "private":
        await message.reply("Салам, боец!\nЯ бот вашей CS2-тусовки.\nℹ️ Пошли в ЛС для управления:",
                            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                [types.InlineKeyboardButton(text="Перейти в ЛС", url=f"t.me/{BOT_USERNAME}")]
                            ]))
        return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1] == "voting" and voting_state.active:
        if user_id in voting_state.participants:
            if user_id in voting_state.voted_users:
                await message.reply("🏆 Вы уже завершили голосование за рейтинг!")
            else:
                keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="Начать голосование", callback_data="start_voting_user")]
                ])
                await message.reply("🏆 Голосование за рейтинг активно! Нажми, чтобы начать:", reply_markup=keyboard)
        else:
            await message.reply("❌ Вы не участвуете в текущем голосовании!")
    else:
        await message.reply("Салам, боец!\nЯ бот вашей CS2-тусовки. Выбери действие:", reply_markup=build_main_menu(user_id))

@dp.callback_query(lambda c: c.data == 'start')
async def start_callback(callback_query: types.CallbackQuery):
    await bot.edit_message_text(
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        text="Салам, боец!\nЯ бот вашей CS2-тусовки. Выбери действие:",
        reply_markup=build_main_menu(callback_query.from_user.id),
        parse_mode="Markdown"
    )
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
    )
    await bot.send_message(callback_query.from_user.id, help_text, parse_mode="Markdown",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                              [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
                          ]))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'my_stats')
async def my_stats_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    response = "❌ Вы не в списке игроков!" if not player else (
        f"*Ваша статистика:*\n\n"
        f"• *Звание:* {player['stats'].get('rank', 'Рядовой')}\n"
        f"• *Очки:* {player['stats'].get('rank_points', 0)}\n"
        f"• *Игр сыграно:* {player['stats'].get('games_played', 0)}\n"
        f"• *MVP:* {player['awards'].get('mvp', 0)} раз\n"
        f"• *1st:* {player['awards'].get('place1', 0)} раз\n"
        f"• *2nd:* {player['awards'].get('place2', 0)} раз\n"
        f"• *3rd:* {player['awards'].get('place3', 0)} раз\n"
        f"• *Прорыв вечера:* {player['awards'].get('breakthrough', 0)} раз\n"
    )
    await bot.send_message(user_id, response, parse_mode="Markdown")
    await bot.answer_callback_query(callback_query.id)

@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    response = "❌ Вы не в списке игроков!" if not player else (
        f"*Ваша статистика:*\n\n"
        f"• *Звание:* {player['stats'].get('rank', 'Рядовой')}\n"
        f"• *Очки:* {player['stats'].get('rank_points', 0)}\n"
        f"• *Игр сыграно:* {player['stats'].get('games_played', 0)}\n"
        f"• *MVP:* {player['awards'].get('mvp', 0)} раз\n"
        f"• *1st:* {player['awards'].get('place1', 0)} раз\n"
        f"• *2nd:* {player['awards'].get('place2', 0)} раз\n"
        f"• *3rd:* {player['awards'].get('place3', 0)} раз\n"
        f"• *Прорыв вечера:* {player['awards'].get('breakthrough', 0)} раз\n"
    )
    await message.reply(response, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == 'list_players')
async def list_players_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = load_players()
    response = "❌ Список игроков пуст!" if not players_data['players'] else (
        "*Список игроков:*\n\n" + "\n".join(
            f"{i}. *{p['name']}* (ID: {p['id']})\n   Звание: {p['stats'].get('rank', 'Рядовой')}, "
            f"Очки: {p['stats'].get('rank_points', 0)}" for i, p in enumerate(players_data['players'], 1)
        )
    )
    await bot.send_message(callback_query.from_user.id, response, parse_mode="Markdown",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                              [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
                          ]))
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
    await bot.send_message(callback_query.from_user.id, "Выберите действие:",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
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
    ] + [[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_players")]]
    await bot.send_message(callback_query.from_user.id, "Выберите игрока для удаления:",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
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
            "stats": {"mvp_count": 0, "games_played": 0, "rank_points": 0, "rank": "Рядовой"}
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
        await message.reply(f"Вы уверены, что хотите удалить игрока с ID {player_id}?",
                            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                [types.InlineKeyboardButton(text="Да", callback_data=f"confirm_remove_{player_id}")],
                                [types.InlineKeyboardButton(text="Нет", callback_data="cancel_remove")]
                            ]))
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
    text = "*Лидерборд игроков:*\n\n" + "\n".join(
        f"• *{i}. {p['name']}* — *{p['stats'].get('rank_points', 0)}* очков" for i, p in enumerate(sorted_players, 1)
    )
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command(commands=['game_players']))
async def game_players(message: types.Message):
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    response = "❌ Нет участников последней игры!" if not participants else (
        "*Участники последней игры:*\n\n" + "\n".join(f"• {p['name']} (ID: {p['id']})" for p in participants)
    )
    await message.reply(response, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == 'start_voting_menu')
async def start_voting_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    await bot.send_message(callback_query.from_user.id, "Управление голосованием:", reply_markup=build_voting_menu())
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data in ['voting_in_progress', 'breakthrough_in_progress'])
async def voting_in_progress(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Голосование уже идёт!")

@dp.callback_query(lambda c: c.data == 'start_voting')
async def start_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_state.active or voting_state.breakthrough_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование уже активно или не завершён предыдущий цикл!")
        return
    players_data = load_players()
    if len(players_data['players']) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно игроков в списке (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.excluded_players = []
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']} (ID: {p['id']})", callback_data=f"exclude_{p['id']}")]
        for p in players_data['players']
    ] + [
        [types.InlineKeyboardButton(text="Подтвердить и начать", callback_data="confirm_voting_start")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start_voting_menu")]
    ]
    await bot.send_message(callback_query.from_user.id, "Выберите игроков, которые НЕ участвовали в последней игре:",
                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data.startswith('exclude_'))
async def exclude_player(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    if player_id not in voting_state.excluded_players:
        voting_state.excluded_players.append(player_id)
        await bot.answer_callback_query(callback_query.id, f"Игрок с ID {player_id} исключён из участников.")
    else:
        voting_state.excluded_players.remove(player_id)
        await bot.answer_callback_query(callback_query.id, f"Игрок с ID {player_id} возвращён в участников.")
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'confirm_voting_start')
async def confirm_voting_start(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['id'] not in voting_state.excluded_players]
    if len(participants) < 2:
        await bot.send_message(callback_query.from_user.id, "❌ Недостаточно участников для голосования (минимум 2)!")
        await bot.answer_callback_query(callback_query.id)
        return
    for p in players_data['players']:
        was_played = p['played_last_game']
        p['played_last_game'] = p['id'] in [player['id'] for player in participants]
        p['ratings'] = []
        if p['played_last_game'] and not was_played:
            p['stats']['games_played'] += 1
    save_players(players_data)
    voting_state.active = True
    voting_state.participants = [p['id'] for p in participants]
    voting_state.voted_users.clear()
    voting_state.voting_messages.clear()
    message = await bot.send_message(GROUP_ID, "🏆 Голосование за рейтинг началось! Участники, перейдите в ЛС для голосования:",
                                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}?start=voting")]
                                    ]))
    voting_state.voting_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, voting_state.voting_message_id, disable_notification=True)
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за рейтинг запущено! Участники начнут голосование в ЛС.")
    for participant_id in voting_state.participants:
        try:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Начать голосование", callback_data="start_voting_user")]
            ])
            await bot.send_message(participant_id, "🏆 Голосование за рейтинг началось! Нажми, чтобы начать:", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"Не удалось уведомить участника {participant_id}: {e}")
    await bot.edit_message_reply_markup(callback_query.from_user.id, callback_query.message.message_id, reply_markup=build_voting_menu())
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'start_voting_user')
async def start_voting_user(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if not voting_state.active:
        await bot.send_message(user_id, "❌ Голосование за рейтинг не активно!")
        await bot.answer_callback_query(callback_query.id)
        return
    if user_id not in voting_state.participants:
        await bot.send_message(user_id, "❌ Вы не участвуете в текущем голосовании!")
        await bot.answer_callback_query(callback_query.id)
        return
    if user_id in voting_state.voted_users:
        await bot.send_message(user_id, "❌ Вы уже завершили голосование!")
        await bot.answer_callback_query(callback_query.id)
        return
    await send_voting_messages(user_id)
    await bot.send_message(user_id, "🏆 Голосование начато! Оцени всех участников.")
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

async def send_voting_messages(user_id: int):
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['id'] in voting_state.participants and p['id'] != user_id]
    voting_state.voting_messages[user_id] = []
    for player in participants:
        inline_keyboard = [
            [types.InlineKeyboardButton(text=str(i), callback_data=f"score_{player['id']}_{i}") for i in range(5, 11)],
            [types.InlineKeyboardButton(text="Меньше 5", callback_data=f"less_{player['id']}")]
        ]
        message = await bot.send_message(user_id, f"🏆 Оцени игрока {player['name']} (от 5 до 10):",
                                        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
        voting_state.voting_messages[user_id].append(message.message_id)
    finish_message = await bot.send_message(user_id, "🏆 Когда оценишь всех, заверши голосование:",
                                          reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                              [types.InlineKeyboardButton(text="Завершить голосование", callback_data="finish_voting_user")]
                                          ]))
    voting_state.voting_messages[user_id].append(finish_message.message_id)
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data.startswith('less_'))
async def rate_less(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants or user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете или уже завершили голосование!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Этот игрок не участвовал!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=str(i), callback_data=f"score_{player_id}_{i}") for i in range(1, 5)],
        [types.InlineKeyboardButton(text="Назад", callback_data=f"rate_back_{player_id}")]
    ]
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"🏆 Оцени игрока {player['name']} (от 1 до 4):",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('rate_back_'))
async def rate_back(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants or user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете или уже завершили голосование!")
        return
    player_id = int(callback_query.data.split('_')[2])
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Этот игрок не участвовал!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=str(i), callback_data=f"score_{player_id}_{i}") for i in range(5, 11)],
        [types.InlineKeyboardButton(text="Меньше 5", callback_data=f"less_{player_id}")]
    ]
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"🏆 Оцени игрока {player['name']} (от 5 до 10):",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('score_'))
async def process_score(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants or user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете или уже завершили голосование!")
        return
    data = callback_query.data.split('_')
    player_id = int(data[1])
    score = int(data[2])
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Этот игрок не участвовал!")
        return
    player['ratings'] = [r for r in player['ratings'] if r['from'] != user_id] + [{'from': user_id, 'score': score}]
    save_players(players_data)
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"✅ Ты поставил оценку {score} игроку {player['name']}",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Изменить оценку", callback_data=f"edit_score_{player_id}")]
        ])
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('edit_score_'))
async def edit_score(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants or user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете или уже завершили голосование!")
        return
    player_id = int(callback_query.data.split('_')[2])
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Этот игрок не участвовал!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=str(i), callback_data=f"score_{player_id}_{i}") for i in range(5, 11)],
        [types.InlineKeyboardButton(text="Меньше 5", callback_data=f"less_{player_id}")]
    ]
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"🏆 Оцени игрока {player['name']} (от 5 до 10):",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'finish_voting_user')
async def finish_voting_user(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants or user_id in voting_state.voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете или уже завершили голосование!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['id'] in voting_state.participants and p['id'] != user_id]
    unrated = [p for p in participants if not any(r['from'] == user_id for r in p['ratings'])]
    if unrated:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=callback_query.message.message_id,
            text=f"❌ Вы не оценили: {', '.join(p['name'] for p in unrated)}. Завершайте после оценки всех!",
            reply_markup=callback_query.message.reply_markup
        )
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.voted_users.append(user_id)
    if user_id in voting_state.voting_messages:
        for msg_id in voting_state.voting_messages[user_id]:
            try:
                await bot.edit_message_reply_markup(chat_id=user_id, message_id=msg_id, reply_markup=None)
            except Exception as e:
                logger.warning(f"Не удалось удалить клавиатуру у сообщения {msg_id}: {e}")
        del voting_state.voting_messages[user_id]
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text="✅ Спасибо за ваши оценки! Вы завершили голосование.",
        reply_markup=None
    )
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)
    if len(voting_state.voted_users) >= len(voting_state.participants) and voting_state.active:
        await check_voting_complete()

@dp.callback_query(lambda c: c.data == 'stop_voting')
async def stop_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование не активно!")
        return
    voting_state.active = False
    if voting_state.voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.voting_message_id)
    await check_voting_complete()
    await bot.send_message(callback_query.from_user.id, "✅ Голосование остановлено!")
    await bot.edit_message_reply_markup(callback_query.from_user.id, callback_query.message.message_id, reply_markup=build_voting_menu())
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'voting_results')
async def voting_results(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование за рейтинг не активно!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['id'] in voting_state.participants]
    response = f"*Промежуточные результаты голосования за рейтинг*:\n\n"
    response += f"Проголосовало: {len(voting_state.voted_users)} из {len(participants)}\n"
    for p in participants:
        avg = sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0
        response += f"• {p['name']}: {avg:.1f} (голосов: {len(p['ratings'])})\n"
    await bot.send_message(callback_query.from_user.id, response, parse_mode="Markdown")
    await bot.answer_callback_query(callback_query.id)

async def calculate_voting_results(players_data: Dict) -> tuple:
    participants = [p for p in players_data['players'] if p['id'] in voting_state.participants]
    sorted_players = sorted(participants, key=lambda p: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0, reverse=True)
    points_map = {1: 25, 2: 20, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 3, 10: 2}
    averages = {p['id']: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0 for p in sorted_players}
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
    return sorted_players, averages, awards_notifications

async def check_voting_complete():
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['id'] in voting_state.participants]
    if not participants:
        return
    sorted_players, averages, awards_notifications = await calculate_voting_results(players_data)
    if voting_state.voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.voting_message_id)
    result = "🏆 *Итоги голосования за рейтинг* 🏆\n\n🎯 *Таблица результатов:*\n"
    for i, p in enumerate(sorted_players, 1):
        avg = averages.get(p['id'], 0)
        result += f"{i}. {p['name']} — {avg:.1f} ★ "
        if i == 1:
            result += "🏅 *MVP*"
        elif i == 2:
            result += "🥇 *1-е место*"
        elif i == 3:
            result += "🥈 *2-е место*"
        elif i == 4:
            result += "🥉 *3-е место*"
        result += "\n"
    result += "\n📣 *Голосование за 'Прорыв вечера' скоро начнётся!*"
    message = await bot.send_message(GROUP_ID, result, parse_mode="Markdown")
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    for participant_id in voting_state.participants:
        await bot.send_message(participant_id, "🏆 Голосование за рейтинг завершено! Проверьте результаты в группе!")
    for winner_id, award_text in awards_notifications:
        await bot.send_message(winner_id, award_text)
    voting_state.active = False
    voting_state.voting_messages.clear()
    await bot.send_message(ADMIN_ID, "✅ Голосование за рейтинг завершено! Запустите 'Прорыв вечера' вручную.", reply_markup=build_voting_menu())
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'start_breakthrough')
async def start_breakthrough(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_state.breakthrough_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование за 'Прорыв вечера' уже активно!")
        return
    if voting_state.active:
        await bot.answer_callback_query(callback_query.id, "❌ Сначала завершите голосование за рейтинг!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    if not participants:
        await bot.send_message(callback_query.from_user.id, "❌ Нет участников для 'Прорыва вечера'!")
        await bot.answer_callback_query(callback_query.id)
        return
    sorted_players = sorted(participants, key=lambda p: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0, reverse=True)
    eligible_players = sorted_players[4:]  # Исключаем топ-4
    if not eligible_players:
        await bot.send_message(callback_query.from_user.id, "❌ Нет кандидатов на 'Прорыв вечера' (все в топ-4)!")
        await bot.answer_callback_query(callback_query.id)
        return
    voting_state.breakthrough_active = True
    voting_state.breakthrough_voted_users.clear()
    message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' началось! Участники, выберите героя в ЛС:",
                                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}")]
                                    ]))
    voting_state.breakthrough_message_id = message.message_id
    await bot.pin_chat_message(GROUP_ID, voting_state.breakthrough_message_id, disable_notification=True)
    for participant_id in voting_state.participants:
        try:
            await send_breakthrough_voting_message(participant_id, sorted_players)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщений участнику {participant_id}: {e}")
    await bot.edit_message_reply_markup(callback_query.from_user.id, callback_query.message.message_id, reply_markup=build_voting_menu())
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' запущено!")
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

async def send_breakthrough_voting_message(user_id: int, sorted_players: List[Dict]):
    eligible_players = sorted_players[4:]
    inline_keyboard = [
        [types.InlineKeyboardButton(text=p['name'], callback_data=f"breakthrough_vote_{p['id']}")]
        for p in eligible_players
    ]
    message = await bot.send_message(user_id, "🚀 Выберите одного игрока для 'Прорыва вечера':",
                                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard))
    voting_state.voting_messages[user_id] = [message.message_id]
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data.startswith('breakthrough_vote_'))
async def breakthrough_vote(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in voting_state.participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    if user_id in voting_state.breakthrough_voted_users:
        await bot.answer_callback_query(callback_query.id, "❌ Вы уже проголосовали за 'Прорыв вечера'!")
        return
    player_id = int(callback_query.data.split('_')[2])
    players_data = load_players()
    player = next((p for p in players_data['players'] if p['id'] == player_id and p['played_last_game']), None)
    if not player:
        await bot.answer_callback_query(callback_query.id, "❌ Этот игрок не участвовал или не подходит!")
        return
    player.setdefault('breakthrough_ratings', []).append({'from': user_id})
    voting_state.breakthrough_voted_users.append(user_id)
    save_players(players_data)
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"✅ Ты выбрал {player['name']} для 'Прорыва вечера'!",
        reply_markup=None
    )
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)
    if len(voting_state.breakthrough_voted_users) >= len(voting_state.participants) and voting_state.breakthrough_active:
        await check_breakthrough_voting_complete()

@dp.callback_query(lambda c: c.data == 'stop_breakthrough')
async def stop_breakthrough(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.breakthrough_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование за 'Прорыв вечера' не активно!")
        return
    voting_state.breakthrough_active = False
    players_data = load_players()
    for p in players_data['players']:
        p['played_last_game'] = False
        p['ratings'] = []
        p.pop('breakthrough_ratings', None)
    save_players(players_data)
    if voting_state.breakthrough_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_message_id)
        await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' остановлено администратором!")
    for participant_id in voting_state.participants:
        if participant_id not in voting_state.breakthrough_voted_users and participant_id in voting_state.voting_messages:
            for msg_id in voting_state.voting_messages[participant_id]:
                await bot.edit_message_reply_markup(chat_id=participant_id, message_id=msg_id, reply_markup=None)
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' было остановлено!")
            del voting_state.voting_messages[participant_id]
    await bot.send_message(callback_query.from_user.id, "✅ Голосование за 'Прорыв вечера' остановлено!")
    await bot.edit_message_reply_markup(callback_query.from_user.id, callback_query.message.message_id, reply_markup=build_voting_menu())
    await bot.answer_callback_query(callback_query.id)
    save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'breakthrough_results')
async def breakthrough_results(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.breakthrough_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование за 'Прорыв вечера' не активно!")
        return
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    sorted_players = sorted(participants, key=lambda p: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0, reverse=True)
    eligible_players = sorted_players[4:]
    response = f"*Промежуточные результаты 'Прорыв вечера'*:\n\n"
    response += f"Проголосовало: {len(voting_state.breakthrough_voted_users)} из {len(voting_state.participants)}\n"
    for p in eligible_players:
        votes = len(p.get('breakthrough_ratings', []))
        response += f"• {p['name']}: {votes} голосов\n"
    await bot.send_message(callback_query.from_user.id, response, parse_mode="Markdown")
    await bot.answer_callback_query(callback_query.id)

async def check_breakthrough_voting_complete():
    players_data = load_players()
    participants = [p for p in players_data['players'] if p['played_last_game']]
    sorted_players = sorted(participants, key=lambda p: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0, reverse=True)
    eligible_players = sorted_players[4:]
    if not eligible_players:
        voting_state.breakthrough_active = False
        message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' завершено!\n\nНет кандидатов.")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
        if voting_state.breakthrough_message_id:
            await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_message_id)
        for p in players_data['players']:
            p['played_last_game'] = False
            p['ratings'] = []
            p.pop('breakthrough_ratings', None)
        save_players(players_data)
        save_voting_state(voting_state)
        return
    sorted_eligible = sorted(eligible_players, key=lambda p: len(p.get('breakthrough_ratings', [])), reverse=True)
    max_votes = len(sorted_eligible[0].get('breakthrough_ratings', [])) if sorted_eligible else 0
    winners = [p for p in sorted_eligible if len(p.get('breakthrough_ratings', [])) == max_votes]
    if winners and (len(voting_state.breakthrough_voted_users) >= len(voting_state.participants) or not voting_state.breakthrough_active):
        voting_state.breakthrough_active = False
        winner_names = ", ".join(p['name'] for p in winners)
        for winner in winners:
            winner['awards']['breakthrough'] += 1
            winner['stats']['rank_points'] += 10
            update_rank(winner)
            await bot.send_message(winner['id'], "🚀 Вы получили награду 'Прорыв вечера' (+10 очков)!")
        result = f"🚀 *Итоги голосования за 'Прорыв вечера'* 🚀\n\n🏆 *Прорыв вечера:* {winner_names}\n🎉 *Поздравляем!*"
        message = await bot.send_message(GROUP_ID, result, parse_mode="Markdown")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
        if voting_state.breakthrough_message_id:
            await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_state.breakthrough_message_id)
        for participant_id in voting_state.participants:
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' завершено! Проверьте результаты!")
        await bot.send_message(ADMIN_ID, "✅ Голосование за 'Прорыв вечера' завершено!", reply_markup=build_voting_menu())
        for p in players_data['players']:
            p['played_last_game'] = False
            p['ratings'] = []
            p.pop('breakthrough_ratings', None)
        save_players(players_data)
        voting_state.voting_messages.clear()
        voting_state.breakthrough_voted_users.clear()
        save_voting_state(voting_state)

@dp.callback_query(lambda c: c.data == 'remind_laggards')
async def remind_laggards(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_state.active and not voting_state.breakthrough_active:
        await bot.answer_callback_query(callback_query.id, "❌ Нет активного голосования!")
        return
    players_data = load_players()
    if voting_state.active:
        laggards = [p for p in players_data['players'] if p['id'] in voting_state.participants and p['id'] not in voting_state.voted_users]
        if not laggards:
            await bot.answer_callback_query(callback_query.id, "Все участники уже проголосовали!")
            return
        mentions = " ".join(f"@id{p['id']}" for p in laggards)
        await bot.send_message(GROUP_ID, f"🏆 Напоминание: {mentions}, пожалуйста, завершите голосование за рейтинг!")
        await bot.answer_callback_query(callback_query.id, "Уведомление отправлено!")
    elif voting_state.breakthrough_active:
        laggards = [p for p in players_data['players'] if p['id'] in voting_state.participants and p['id'] not in voting_state.breakthrough_voted_users]
        if not laggards:
            await bot.answer_callback_query(callback_query.id, "Все участники уже проголосовали!")
            return
        mentions = " ".join(f"@id{p['id']}" for p in laggards)
        await bot.send_message(GROUP_ID, f"🚀 Напоминание: {mentions}, пожалуйста, проголосуйте за 'Прорыв вечера'!")
        await bot.answer_callback_query(callback_query.id, "Уведомление отправлено!")

@dp.callback_query(lambda c: c.data == 'user_voting_menu')
async def user_voting_menu(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players_data = load_players()
    user_participated = any(p['id'] == user_id and p['played_last_game'] for p in players_data['players'])
    if not user_participated:
        await bot.send_message(user_id, "❌ Вы не участвовали в последней игре!")
        await bot.answer_callback_query(callback_query.id)
        return
    if voting_state.active:
        if user_id in voting_state.voted_users:
            await bot.send_message(user_id, "🏆 Вы уже завершили голосование за рейтинг!")
        else:
            await bot.send_message(user_id, "🏆 Голосование за рейтинг активно! Нажми, чтобы начать:",
                                  reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                                      [types.InlineKeyboardButton(text="Начать голосование за рейтинг", callback_data="start_voting_user")]
                                  ]))
    elif voting_state.breakthrough_active:
        if user_id in voting_state.breakthrough_voted_users:
            await bot.send_message(user_id, "🚀 Вы уже проголосовали за 'Прорыв вечера'!")
        else:
            participants = [p for p in players_data['players'] if p['played_last_game']]
            sorted_players = sorted(participants, key=lambda p: sum(r['score'] for r in p['ratings']) / max(1, len(p['ratings'])) if p['ratings'] else 0, reverse=True)
            await send_breakthrough_voting_message(user_id, sorted_players)
            await bot.send_message(user_id, "🚀 Голосование за 'Прорыв вечера' начато! Выбери одного игрока.")
    else:
        await bot.send_message(user_id, "❌ Нет активного голосования!")
    await bot.answer_callback_query(callback_query.id)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def on_startup(dispatcher):
    global voting_state
    if not os.path.exists('players.json'):
        await fetch_players_from_github()
    if not os.path.exists(STATE_FILE):
        voting_state = await fetch_voting_state_from_github()
    else:
        voting_state = load_voting_state()
    
    # Уведомление только админу при перезапуске
    if (voting_state.active or voting_state.breakthrough_active) and not voting_state.restart_notified:
        message_text = (
            "⚠️ Бот перезапустился.\n"
            f"Голосование за рейтинг: {'активно' if voting_state.active else 'неактивно'}.\n"
            f"Голосование за 'Прорыв вечера': {'активно' if voting_state.breakthrough_active else 'неактивно'}.\n"
            "Состояние восстановлено."
        )
        await bot.send_message(ADMIN_ID, message_text)
        voting_state.restart_notified = True
        
        # Восстановление сообщения в группе для голосования за рейтинг
        if voting_state.active and voting_state.voting_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=GROUP_ID,
                    message_id=voting_state.voting_message_id,
                    text="🏆 Голосование за рейтинг началось! Участники, перейдите в ЛС для голосования:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}?start=voting")]
                    ])
                )
                await bot.pin_chat_message(GROUP_ID, voting_state.voting_message_id, disable_notification=True)
            except Exception as e:
                logger.error(f"Не удалось восстановить сообщение для голосования за рейтинг: {e}")
                new_message = await bot.send_message(
                    GROUP_ID,
                    "🏆 Голосование за рейтинг началось! Участники, перейдите в ЛС для голосования:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}?start=voting")]
                    ])
                )
                voting_state.voting_message_id = new_message.message_id
                await bot.pin_chat_message(GROUP_ID, voting_state.voting_message_id, disable_notification=True)
        
        # Восстановление сообщения в группе для "Прорыва вечера"
        if voting_state.breakthrough_active and voting_state.breakthrough_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=GROUP_ID,
                    message_id=voting_state.breakthrough_message_id,
                    text="🚀 Голосование за 'Прорыв вечера' началось! Участники, выберите героя в ЛС:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}")]
                    ])
                )
                await bot.pin_chat_message(GROUP_ID, voting_state.breakthrough_message_id, disable_notification=True)
            except Exception as e:
                logger.error(f"Не удалось восстановить сообщение для 'Прорыва вечера': {e}")
                new_message = await bot.send_message(
                    GROUP_ID,
                    "🚀 Голосование за 'Прорыв вечера' началось! Участники, выберите героя в ЛС:",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="Проголосовать", url=f"t.me/{BOT_USERNAME}")]
                    ])
                )
                voting_state.breakthrough_message_id = new_message.message_id
                await bot.pin_chat_message(GROUP_ID, voting_state.breakthrough_message_id, disable_notification=True)
        
        save_voting_state(voting_state)
    
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Бот запущен с вебхуком: %s", WEBHOOK_URL)

async def on_shutdown(dispatcher):
    logger.info("Сохранение данных перед завершением")
    if players_data_cache is not None:
        save_players(players_data_cache)
    save_voting_state(voting_state)
    await bot.delete_webhook()
    logger.info("Бот остановлен")

async def main():
    app = web.Application()
    webhook_request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_request_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get('/', health_check)
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
