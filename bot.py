import os
import json
import asyncio
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Токен бота
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'
GIT_REPO_URL = f"https://{os.getenv('GIT_TOKEN')}@github.com/ildarkhan12/cs2-bot.git"

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Твои ID
ADMIN_ID = 113405030
GROUP_ID = -1002484381098  # Правильный ID группы

# Флаги состояния голосования
voting_active = False
breakthrough_voting_active = False

# Функции для работы с файлами и Git
def load_players():
    if not os.path.exists('players.json'):
        with open('players.json', 'w', encoding='utf-8') as f:
            json.dump({"players": []}, f, ensure_ascii=False, indent=4)
    with open('players.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def save_players(players_data):
    with open('players.json', 'w', encoding='utf-8') as f:
        json.dump(players_data, f, ensure_ascii=False, indent=4)
    try:
        result = subprocess.run(['git', 'status', '--porcelain', 'players.json'], capture_output=True, text=True)
        if result.stdout.strip():
            subprocess.run(['git', 'config', 'user.email', 'bot@example.com'], check=True)
            subprocess.run(['git', 'config', 'user.name', 'CS2Bot'], check=True)
            subprocess.run(['git', 'add', 'players.json'], check=True)
            subprocess.run(['git', 'commit', '-m', 'Update players.json'], check=True)
            subprocess.run(['git', 'push', GIT_REPO_URL, 'HEAD:main'], check=True)
            print("players.json успешно сохранён в GitHub")
        else:
            print("Нет изменений в players.json для коммита")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при сохранении players.json в Git: {e}")

def load_maps():
    if not os.path.exists('maps.json'):
        default_maps = {map_name: 0 for map_name in ["Dust2", "Mirage", "Inferno", "Nuke", "Overpass", "Vertigo", "Ancient", "Anubis", "Cache", "Train"]}
        with open('maps.json', 'w', encoding='utf-8') as f:
            json.dump(default_maps, f, ensure_ascii=False, indent=4)
    with open('maps.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def save_maps(maps_data):
    with open('maps.json', 'w', encoding='utf-8') as f:
        json.dump(maps_data, f, ensure_ascii=False, indent=4)
    try:
        result = subprocess.run(['git', 'status', '--porcelain', 'maps.json'], capture_output=True, text=True)
        if result.stdout.strip():
            subprocess.run(['git', 'config', 'user.email', 'bot@example.com'], check=True)
            subprocess.run(['git', 'config', 'user.name', 'CS2Bot'], check=True)
            subprocess.run(['git', 'add', 'maps.json'], check=True)
            subprocess.run(['git', 'commit', '-m', 'Update maps.json'], check=True)
            subprocess.run(['git', 'push', GIT_REPO_URL, 'HEAD:main'], check=True)
            print("maps.json успешно сохранён в GitHub")
        else:
            print("Нет изменений в maps.json для коммита")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при сохранении maps.json в Git: {e}")

# Функция для отображения текущих результатов
async def show_current_results(chat_id):
    players = load_players()['players']
    result = "🏆 **Текущие результаты голосования**:\n\n"
    for player in players:
        if player['ratings']:
            avg_rating = sum(player['ratings']) / len(player['ratings'])
            result += f"{player['name']} — {avg_rating:.2f} (оценок: {len(player['ratings'])})\n"
        else:
            result += f"{player['name']} — 0.00 (оценок: 0)\n"
    result += "\nℹ️ Это промежуточные данные, голосование ещё идёт!"
    await bot.send_message(chat_id, result, parse_mode='Markdown')

# Проверка завершения основного голосования и запуск голосования за "Прорыв вечера"
async def check_voting_complete():
    global voting_active, breakthrough_voting_active
    players = load_players()['players']
    participants = [p for p in players if p['played_last_game']]
    if not participants:
        return False
    total_participants = len(participants)
    for player in participants:
        expected_ratings = total_participants - 1  # Каждый оценивает всех, кроме себя
        if len(player['ratings']) != expected_ratings:
            return False
    # Все участники проголосовали
    sorted_players = sorted(players, key=lambda p: sum(p['ratings']) / len(p['ratings']) if p['ratings'] else 0, reverse=True)
    for player in players:
        if player['ratings']:
            avg_rating = sum(player['ratings']) / len(player['ratings'])
            player['stats']['avg_rating'] = avg_rating
            player['ratings'] = []
    if sorted_players:
        sorted_players[0]['awards']['mvp'] += 1
        sorted_players[0]['stats']['mvp_count'] += 1
    if len(sorted_players) >= 2:
        sorted_players[1]['awards']['place1'] += 1
    if len(sorted_players) >= 3:
        sorted_players[2]['awards']['place2'] += 1
    if len(sorted_players) >= 4:
        sorted_players[3]['awards']['place3'] += 1
    save_players({"players": players})
    result = "🏆 **Результаты боя**:\n\n"
    for i, p in enumerate(sorted_players, 1):
        awards_str = ""
        awards = p['awards']
        if awards['mvp'] > 0:
            awards_str += f" (MVP 🏆: {awards['mvp']})"
        elif awards['place1'] > 0:
            awards_str += f" (🥇 1st: {awards['place1']})"
        elif awards['place2'] > 0:
            awards_str += f" (🥈 2nd: {awards['place2']})"
        elif awards['place3'] > 0:
            awards_str += f" (🥉 3rd: {awards['place3']})"
        result += f"{i}. {p['name']} — {p['stats']['avg_rating']:.2f}{awards_str}\n"
    await bot.send_message(GROUP_ID, result, parse_mode='Markdown')
    await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено автоматически! Запускаем голосование за 'Прорыв вечера'.")
    voting_active = False
    breakthrough_voting_active = True
    await start_breakthrough_voting()
    return True

# Запуск голосования за "Прорыв вечера"
async def start_breakthrough_voting():
    players = load_players()['players']
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.send_message(GROUP_ID, "🚀 Нет кандидатов на 'Прорыв вечера'!")
        return
    inline_keyboard = [[types.InlineKeyboardButton(text="Голосовать за 'Прорыв вечера'", callback_data="vote_breakthrough")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' началось! Оцени игрока, показавшего лучший прогресс (не из топ-4):", reply_markup=keyboard)

# Проверка завершения голосования за "Прорыв вечера"
async def check_breakthrough_voting_complete():
    global breakthrough_voting_active
    players = load_players()['players']
    participants = [p for p in players if p['played_last_game']]
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        breakthrough_voting_active = False
        return True
    total_participants = len(participants)
    for player in eligible_players:
        expected_ratings = total_participants  # Каждый может оценить одного игрока
        if len(player.get('breakthrough_ratings', [])) != expected_ratings:
            return False
    # Все участники проголосовали
    sorted_eligible = sorted(eligible_players, key=lambda p: sum(p['breakthrough_ratings']) / len(p['breakthrough_ratings']) if p['breakthrough_ratings'] else 0, reverse=True)
    if sorted_eligible:
        sorted_eligible[0]['awards']['breakthrough'] = sorted_eligible[0]['awards'].get('breakthrough', 0) + 1
        await bot.send_message(GROUP_ID, f"🚀 **Прорыв вечера**: {sorted_eligible[0]['name']}!")
    for player in players:
        player.pop('breakthrough_ratings', None)  # Очищаем временные рейтинги
    save_players({"players": players})
    breakthrough_voting_active = False
    return True

# Команда /start
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    welcome_text = ("Салам, боец!\n"
                    "Я бот вашей CS2-тусовки. Вот что я умею:\n"
                    "🏆 Проводить голосования за рейтинг и карты\n"
                    "🎖 Присуждать награды\n"
                    "📊 Показывать статистику\n\n"
                    "ℹ️ Выбери действие ниже:")
    
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
            ],
            [
                types.InlineKeyboardButton(text="Голосование за карты", callback_data="start_map_voting_menu")
            ]
        ])
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.reply(welcome_text, reply_markup=keyboard)

# Обработка кнопки "Список команд"
@dp.callback_query(lambda c: c.data == 'help')
async def process_help(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        help_text = ("📜 **Список команд**:\n"
                     "/start — начать работу\n"
                     "/my_stats — твоя статистика\n"
                     "/top — показать топ игроков\n"
                     "**Для админа**:\n"
                     "/add_player \[ID\] \[имя\] — добавить игрока\n"
                     "/remove_player \[ID\] — удалить игрока")
    else:
        help_text = ("📜 **Список команд**:\n"
                     "/start — начать работу\n"
                     "/my_stats — твоя статистика\n"
                     "/top — показать топ игроков\n"
                     "ℹ️ Если ты участвовал в последней игре, сможешь голосовать за рейтинг!")
    await bot.send_message(callback_query.from_user.id, help_text, parse_mode='Markdown')
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Моя статистика"
@dp.callback_query(lambda c: c.data == 'my_stats')
async def process_my_stats(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    player = next((p for p in players if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (f"📊 **Твоя статистика**:\n"
                    f"Средний рейтинг: {stats['avg_rating']:.2f}\n"
                    f"MVP: {awards.get('mvp', 0)} раз\n"
                    f"1st: {awards.get('place1', 0)} раз\n"
                    f"2nd: {awards.get('place2', 0)} раз\n"
                    f"3rd: {awards.get('place3', 0)} раз\n"
                    f"Прорыв вечера: {awards.get('breakthrough', 0)} раз")
        await bot.send_message(user_id, response, parse_mode='Markdown')
    else:
        await bot.send_message(user_id, "❌ Ты не в списке игроков!")
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Управление игроками" (админ)
@dp.callback_query(lambda c: c.data == 'manage_players')
async def manage_players(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Добавить игрока", callback_data="add_player_menu"),
            types.InlineKeyboardButton(text="Удалить игрока", callback_data="remove_player_menu")
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выбери действие:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Меню "Добавить игрока" (админ)
@dp.callback_query(lambda c: c.data == 'add_player_menu')
async def add_player_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    await bot.send_message(callback_query.from_user.id, "Напиши: /add_player [ID] [имя]\nНапример: /add_player 123456789 Иван")
    await bot.answer_callback_query(callback_query.id)

# Меню "Удалить игрока" (админ)
@dp.callback_query(lambda c: c.data == 'remove_player_menu')
async def remove_player_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players = load_players()['players']
    if not players:
        await bot.send_message(callback_query.from_user.id, "Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    inline_keyboard = [[types.InlineKeyboardButton(text=f"{player['name']} (ID: {player['id']})", callback_data=f"remove_{player['id']}")] for player in players]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выбери игрока для удаления:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Удаление игрока через кнопку
@dp.callback_query(lambda c: c.data.startswith('remove_'))
async def process_remove_player(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    players_data['players'] = [p for p in players_data['players'] if p['id'] != player_id]
    save_players(players_data)
    await bot.send_message(callback_query.from_user.id, f"✅ Игрок с ID {player_id} удалён!")
    await bot.answer_callback_query(callback_query.id)

# Меню "Голосование за рейтинг" (админ)
@dp.callback_query(lambda c: c.data == 'start_voting_menu')
async def start_voting_menu(callback_query: types.CallbackQuery):
    global voting_active, breakthrough_voting_active
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_active or breakthrough_voting_active:
        inline_keyboard = [
            [
                types.InlineKeyboardButton(text="В процессе", callback_data="voting_active"),
                types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_voting")
            ],
            [types.InlineKeyboardButton(text="Текущие результаты", callback_data="current_results")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(callback_query.from_user.id, "Голосование уже идёт!", reply_markup=keyboard)
        await bot.answer_callback_query(callback_query.id)
        return
    players = load_players()['players']
    if not players:
        await bot.send_message(callback_query.from_user.id, "Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    for player in players:
        player['played_last_game'] = True
    save_players({"players": players})
    
    inline_keyboard = [[types.InlineKeyboardButton(text=f"{player['name']} (ID: {player['id']})", callback_data=f"absent_{player['id']}")] for player in players]
    inline_keyboard.append([types.InlineKeyboardButton(text="Готово", callback_data="finish_voting_setup")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выбери игроков, которые НЕ участвовали в последней игре:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Отметка неучастника
@dp.callback_query(lambda c: c.data.startswith('absent_'))
async def mark_absent(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player['played_last_game'] = False
            await bot.answer_callback_query(callback_query.id, f"{player['name']} отмечен как неучастник!")
            break
    save_players(players_data)

# Завершение настройки голосования
@dp.callback_query(lambda c: c.data == 'finish_voting_setup')
async def finish_voting_setup(callback_query: types.CallbackQuery):
    global voting_active
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players = load_players()['players']
    participants = [p['name'] for p in players if p['played_last_game']]
    absentees = [p['name'] for p in players if not p['played_last_game']]
    response = "✅ Участники последней игры отмечены!\n"
    response += f"Играли: {', '.join(participants) if participants else 'никто'}\n"
    response += f"Не играли: {', '.join(absentees) if absentees else 'никто'}\n"
    response += "Выбери действие:"
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Запустить голосование", callback_data="launch_voting") if not voting_active else types.InlineKeyboardButton(text="В процессе", callback_data="voting_active"),
            types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_voting") if voting_active else types.InlineKeyboardButton(text="Голосование не начато", callback_data="voting_not_started")
        ]
    ]
    if not voting_active:
        inline_keyboard.append([types.InlineKeyboardButton(text="Текущие результаты", callback_data="current_results")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, response, reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Запуск голосования за рейтинг
@dp.callback_query(lambda c: c.data == 'launch_voting')
async def launch_voting(callback_query: types.CallbackQuery):
    global voting_active
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование уже идёт!")
        return
    voting_active = True
    inline_keyboard = [[types.InlineKeyboardButton(text="Голосовать", callback_data="vote")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(GROUP_ID, "🏆 Голосование началось! Нажми кнопку, чтобы оценить игроков (только участники последней игры):", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Показ текущих результатов
@dp.callback_query(lambda c: c.data == 'current_results')
async def current_results(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    await show_current_results(callback_query.from_user.id)
    await bot.answer_callback_query(callback_query.id, "Текущие результаты показаны!")

# Остановка голосования за рейтинг (ручная)
@dp.callback_query(lambda c: c.data == 'stop_voting')
async def stop_voting(callback_query: types.CallbackQuery):
    global voting_active, breakthrough_voting_active
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if not voting_active and not breakthrough_voting_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование не активно!")
        return
    players = load_players()['players']
    if voting_active:
        sorted_players = sorted(players, key=lambda p: sum(p['ratings']) / len(p['ratings']) if p['ratings'] else 0, reverse=True)
        for player in players:
            if player['ratings']:
                avg_rating = sum(player['ratings']) / len(player['ratings'])
                player['stats']['avg_rating'] = avg_rating
                player['ratings'] = []
        if sorted_players:
            sorted_players[0]['awards']['mvp'] += 1
            sorted_players[0]['stats']['mvp_count'] += 1
        if len(sorted_players) >= 2:
            sorted_players[1]['awards']['place1'] += 1
        if len(sorted_players) >= 3:
            sorted_players[2]['awards']['place2'] += 1
        if len(sorted_players) >= 4:
            sorted_players[3]['awards']['place3'] += 1
        save_players({"players": players})
        result = "🏆 **Результаты боя**:\n\n"
        for i, p in enumerate(sorted_players, 1):
            awards_str = ""
            awards = p['awards']
            if awards['mvp'] > 0:
                awards_str += f" (MVP 🏆: {awards['mvp']})"
            elif awards['place1'] > 0:
                awards_str += f" (🥇 1st: {awards['place1']})"
            elif awards['place2'] > 0:
                awards_str += f" (🥈 2nd: {awards['place2']})"
            elif awards['place3'] > 0:
                awards_str += f" (🥉 3rd: {awards['place3']})"
            result += f"{i}. {p['name']} — {p['stats']['avg_rating']:.2f}{awards_str}\n"
        await bot.send_message(GROUP_ID, result, parse_mode='Markdown')
        await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено вручную! Запускаем голосование за 'Прорыв вечера'.")
        voting_active = False
        breakthrough_voting_active = True
        await start_breakthrough_voting()
    elif breakthrough_voting_active:
        eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
        sorted_eligible = sorted(eligible_players, key=lambda p: sum(p.get('breakthrough_ratings', [])) / len(p['breakthrough_ratings']) if p.get('breakthrough_ratings', []) else 0, reverse=True)
        if sorted_eligible:
            sorted_eligible[0]['awards']['breakthrough'] = sorted_eligible[0]['awards'].get('breakthrough', 0) + 1
            await bot.send_message(GROUP_ID, f"🚀 **Прорыв вечера**: {sorted_eligible[0]['name']}!")
        for player in players:
            player.pop('breakthrough_ratings', None)
        save_players({"players": players})
        breakthrough_voting_active = False
        await bot.send_message(ADMIN_ID, "✅ Голосование за 'Прорыв вечера' завершено вручную!")
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Голосовать" (основное голосование)
@dp.callback_query(lambda c: c.data == 'vote')
async def process_start_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    if user_id not in [p['id'] for p in players]:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не в списке игроков!")
        return
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвовал в последней игре!")
        return
    participants = [p for p in players if p['played_last_game'] and p['id'] != user_id]
    for p in participants:
        inline_keyboard = [
            [
                types.InlineKeyboardButton(text="5", callback_data=f"rate_{p['id']}_5"),
                types.InlineKeyboardButton(text="6", callback_data=f"rate_{p['id']}_6"),
                types.InlineKeyboardButton(text="7", callback_data=f"rate_{p['id']}_7"),
            ],
            [
                types.InlineKeyboardButton(text="8", callback_data=f"rate_{p['id']}_8"),
                types.InlineKeyboardButton(text="9", callback_data=f"rate_{p['id']}_9"),
                types.InlineKeyboardButton(text="10", callback_data=f"rate_{p['id']}_10"),
            ],
            [
                types.InlineKeyboardButton(text="Ещё", callback_data=f"more_rates_{p['id']}")
            ]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(user_id, f"Оцени {p['name']} (5-10):", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id, "Проверь личку для голосования!")

# Обработка кнопки "Ещё"
@dp.callback_query(lambda c: c.data.startswith('more_rates_'))
async def more_rates(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    player_id = int(callback_query.data.split('_')[2])
    players = load_players()['players']
    player = next((p for p in players if p['id'] == player_id), None)
    if not player:
        await bot.answer_callback_query(callback_query.id, "❌ Игрок не найден!")
        return
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="1", callback_data=f"rate_{player_id}_1"),
            types.InlineKeyboardButton(text="2", callback_data=f"rate_{player_id}_2"),
            types.InlineKeyboardButton(text="3", callback_data=f"rate_{player_id}_3"),
            types.InlineKeyboardButton(text="4", callback_data=f"rate_{player_id}_4")
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(user_id, f"Оцени {player['name']} (1-4):", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Сохранение оценок и изменение сообщения (основное голосование)
@dp.callback_query(lambda c: c.data.startswith('rate_'))
async def process_rating(callback_query: types.CallbackQuery):
    global voting_active
    data = callback_query.data.split('_')
    player_id = int(data[1])
    rating = int(data[2])
    user_id = callback_query.from_user.id
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player['ratings'].append(rating)
            save_players(players_data)
            new_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Изменить оценку", callback_data=f"edit_rate_{player_id}")]
            ])
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Ты поставил {rating} игроку {player['name']}!",
                reply_markup=new_keyboard
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_voting_complete():
        print("Голосование автоматически завершено!")

# Обработка кнопки "Изменить оценку" (основное голосование)
@dp.callback_query(lambda c: c.data.startswith('edit_rate_'))
async def edit_rating(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    player_id = int(callback_query.data.split('_')[2])
    players = load_players()['players']
    player = next((p for p in players if p['id'] == player_id), None)
    if not player:
        await bot.answer_callback_query(callback_query.id, "❌ Игрок не найден!")
        return
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="5", callback_data=f"rate_{player_id}_5"),
            types.InlineKeyboardButton(text="6", callback_data=f"rate_{player_id}_6"),
            types.InlineKeyboardButton(text="7", callback_data=f"rate_{player_id}_7"),
        ],
        [
            types.InlineKeyboardButton(text="8", callback_data=f"rate_{player_id}_8"),
            types.InlineKeyboardButton(text="9", callback_data=f"rate_{player_id}_9"),
            types.InlineKeyboardButton(text="10", callback_data=f"rate_{player_id}_10"),
        ],
        [
            types.InlineKeyboardButton(text="Ещё", callback_data=f"more_rates_{player_id}")
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"Оцени {player['name']} (5-10):",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Голосовать за 'Прорыв вечера'"
@dp.callback_query(lambda c: c.data == 'vote_breakthrough')
async def process_breakthrough_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    if user_id not in [p['id'] for p in players]:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не в списке игроков!")
        return
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвовал в последней игре!")
        return
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.answer_callback_query(callback_query.id, "❌ Нет кандидатов на 'Прорыв вечера'!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']}", callback_data=f"breakthrough_{p['id']}_{i}")] for i, p in enumerate(eligible_players)
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(user_id, "Выбери игрока для 'Прорыва вечера':", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id, "Проверь личку для голосования!")

# Сохранение голоса за "Прорыв вечера"
@dp.callback_query(lambda c: c.data.startswith('breakthrough_'))
async def process_breakthrough_rating(callback_query: types.CallbackQuery):
    global breakthrough_voting_active
    data = callback_query.data.split('_')
    player_id = int(data[1])
    user_id = callback_query.from_user.id
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            if 'breakthrough_ratings' not in player:
                player['breakthrough_ratings'] = []
            player['breakthrough_ratings'].append(1)  # Каждый голос — 1 балл
            save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Ты проголосовал за {player['name']} как 'Прорыв вечера'!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_breakthrough_voting_complete():
        print("Голосование за 'Прорыв вечера' автоматически завершено!")

# Меню "Голосование за карты" (админ)
@dp.callback_query(lambda c: c.data == 'start_map_voting_menu')
async def start_map_voting_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    maps = ["Dust2", "Mirage", "Inferno", "Nuke", "Overpass", "Vertigo", "Ancient", "Anubis", "Cache", "Train"]
    inline_keyboard = [
        [types.InlineKeyboardButton(text=maps[i], callback_data=f"vote_map_{maps[i]}"),
         types.InlineKeyboardButton(text=maps[i+1], callback_data=f"vote_map_{maps[i+1]}")] for i in range(0, len(maps), 2)
    ]
    inline_keyboard.append([
        types.InlineKeyboardButton(text="Запустить голосование", callback_data="launch_map_voting"),
        types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_map_voting")
    ])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(GROUP_ID, "🗺 Выбери карты для следующего боя или управляй голосованием:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Запуск голосования за карты
@dp.callback_query(lambda c: c.data == 'launch_map_voting')
async def launch_map_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    await bot.send_message(GROUP_ID, "🗺 Голосование за карты началось! Выбери карты выше.")
    await bot.answer_callback_query(callback_query.id)

# Остановка голосования за карты
@dp.callback_query(lambda c: c.data == 'stop_map_voting')
async def stop_map_voting(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    maps_data = load_maps()
    sorted_maps = sorted(maps_data.items(), key=lambda x: x[1], reverse=True)[:5]
    result = "🗺 **Топ-5 карт**:\n"
    for i, (map_name, votes) in enumerate(sorted_maps, 1):
        result += f"{i}. {map_name} — {votes} голосов\n"
    await bot.send_message(GROUP_ID, result, parse_mode='Markdown')
    save_maps({map_name: 0 for map_name in maps_data})
    await bot.answer_callback_query(callback_query.id, "Голосование за карты завершено!")

# Обработка голосов за карты
@dp.callback_query(lambda c: c.data.startswith('vote_map_'))
async def process_map_voting(callback_query: types.CallbackQuery):
    map_name = callback_query.data.split('_')[2]
    maps_data = load_maps()
    maps_data[map_name] += 1
    save_maps(maps_data)
    await bot.answer_callback_query(callback_query.id, f"Ты проголосовал за {map_name}!")

# Команда /add_player (админ) с проверкой на дубли
@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply("ℹ️ Используй: /add_player [ID] [имя]")
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
            "played_last_game": True,
            "awards": {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0},
            "stats": {"avg_rating": 0, "mvp_count": 0}
        })
        save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

# Команда /top
@dp.message(Command(commands=['top']))
async def top_players(message: types.Message):
    players = load_players()['players']
    sorted_players = sorted(players, key=lambda p: p['stats'].get('avg_rating', 0), reverse=True)
    result = "🎖 **ТОП**:\n"
    mvp_player = next((p for p in sorted_players if p['awards']['mvp'] > 0), None)
    place1_player = next((p for p in sorted_players if p['awards']['place1'] > 0), None)
    place2_player = next((p for p in sorted_players if p['awards']['place2'] > 0), None)
    place3_player = next((p for p in sorted_players if p['awards']['place3'] > 0), None)
    breakthrough_player = next((p for p in sorted_players if p['awards'].get('breakthrough', 0) > 0), None)
    if mvp_player:
        result += f"👑 MVP: {mvp_player['name']}\n"
    if place1_player:
        result += f"🥇 1st: {place1_player['name']}\n"
    if place2_player:
        result += f"🥈 2nd: {place2_player['name']}\n"
    if place3_player:
        result += f"🥉 3rd: {place3_player['name']}\n"
    if breakthrough_player:
        result += f"\n🚀 Прорыв вечера: {breakthrough_player['name']}"
    await message.reply(result, parse_mode='Markdown')

# Команда /my_stats
@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players = load_players()['players']
    player = next((p for p in players if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (f"📊 **Твоя статистика**:\n"
                    f"Средний рейтинг: {stats['avg_rating']:.2f}\n"
                    f"MVP: {awards.get('mvp', 0)} раз\n"
                    f"1st: {awards.get('place1', 0)} раз\n"
                    f"2nd: {awards.get('place2', 0)} раз\n"
                    f"3rd: {awards.get('place3', 0)} раз\n"
                    f"Прорыв вечера: {awards.get('breakthrough', 0)} раз")
        await message.reply(response, parse_mode='Markdown')
    else:
        await message.reply("❌ Ты не в списке игроков!")

# Настройка Webhook и Git при запуске
async def on_startup(_):
    try:
        subprocess.run(['git', 'checkout', 'main'], check=True)
        subprocess.run(['git', 'config', 'user.email', 'bot@example.com'], check=True)
        subprocess.run(['git', 'config', 'user.name', 'CS2Bot'], check=True)
        subprocess.run(['git', 'pull', GIT_REPO_URL, 'main'], check=True)
        print("Git успешно настроен и синхронизирован с веткой main")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка настройки Git при запуске: {e}")
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook установлен на {WEBHOOK_URL}")

# Запуск бота через aiohttp
app = web.Application()
handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
handler.register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    web.run_app(app, host='0.0.0.0', port=port)
