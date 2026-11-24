import discord
from discord.ext import tasks
import aiohttp
import functools
import io
import json
import os
import random
import re
import tempfile
import traceback
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def env_id(name: str) -> int:
    """Discord ID (server, role, channel, forum tag) from .env; 0 = not set."""
    return int(os.getenv(name) or 0)


# ==================================================================
#                          CONFIG
# ==================================================================
TOKEN = os.getenv("TOKEN")
# server icon shown in panel and ticket embeds (empty = none)
BRAND_ICON_URL = os.getenv("BRAND_ICON_URL") or None
# invite link printed on the weekly card (empty = none)
INVITE_URL = os.getenv("INVITE_URL", "")
GUILD_ID = env_id("GUILD_ID") # ВСТАВЬ ID сервера (ПКМ по иконке -> Copy Server ID)

# --- roles ---
GATE_ROLE_ID = env_id("GATE_ROLE_ID")      # choose-concept
NEWBIE_ROLE_ID = env_id("NEWBIE_ROLE_ID")    # Newbie - базовая роль доступа к серверу
MEMBER_ROLE_ID = env_id("MEMBER_ROLE_ID")    # Member - выдаётся админом вместо Newbie
LEGEND_ROLE_ID = env_id("LEGEND_ROLE_ID")    # Legend
ADMIN_ROLE_ID = env_id("ADMIN_ROLE_ID")     # HADM
MODER_ROLE_ID = env_id("MODER_ROLE_ID")     # MDR

# роли, которым НЕ начисляются R (но респект давать могут)
NO_POINTS_ROLE_IDS = [ADMIN_ROLE_ID, MODER_ROLE_ID]

# статусные роли: снимаются при уходе в choose-concept и возвращаются после выбора
STATUS_ROLE_IDS = [NEWBIE_ROLE_ID, MEMBER_ROLE_ID, LEGEND_ROLE_ID]
# кого никогда не запирать обратно в choose-concept
GATE_EXEMPT_ROLE_IDS = [ADMIN_ROLE_ID, MODER_ROLE_ID]

# Служебные аккаунты (закупленные под бусты). Живыми участниками не являются,
# поэтому не идут в статистику, не портят воронку новичков и не получают DM.
SERVICE_ROLE_ID = env_id("SERVICE_ROLE_ID")

# --- channels ---
ADMIN_LOG_CHANNEL_ID = env_id("ADMIN_LOG_CHANNEL_ID")  # welcome-adm (входы/выходы/инвайты)
TRANSCRIPT_CHANNEL_ID = env_id("TRANSCRIPT_CHANNEL_ID")  # tickets-archive (транскрипты тикетов)
NEWS_CHANNEL_ID = env_id("NEWS_CHANNEL_ID")
GEO_CHANNEL_ID = 0  # (парсит отдельный скрипт tg_parser, тут не нужен)
LEADERBOARD_CHANNEL_ID = env_id("LEADERBOARD_CHANNEL_ID")
TICKET_CATEGORY_ID = env_id("TICKET_CATEGORY_ID")

# --- trades/backtests forums (для реакций и начисления R) ---
TEAM_TRADES_CHANNEL_ID = env_id("TEAM_TRADES_CHANNEL_ID")   # орёл
USER_TRADES_CHANNEL_ID = env_id("USER_TRADES_CHANNEL_ID")   # плюс/минус
PREMARKETS_CHANNEL_ID = env_id("PREMARKETS_CHANNEL_ID")   # ВСТАВЬ ID форума premarkets (для начисления R)
BACKTESTS_CHANNEL_ID = env_id("BACKTESTS_CHANNEL_ID")      # backtests форум

# --- news roles ---
NEWS_RED_ROLE_ID = env_id("NEWS_RED_ROLE_ID")
NEWS_ORANGE_ROLE_ID = env_id("NEWS_ORANGE_ROLE_ID")
NEWS_GEO_ROLE_ID = env_id("NEWS_GEO_ROLE_ID")
DIGEST_HOUR = 8         # утренний дайджест, час по европейскому времени
DIGEST_WINDOW_HOURS = 3 # сколько часов после DIGEST_HOUR дайджест ещё актуален
ALERT_MINUTES = 15      # пинг за N минут до новости
RESULT_MINUTES = 10     # итог новости через N минут после выхода

# --- custom emoji ---
E_LOGO = os.getenv("E_LOGO") or "📈"
E_EAGLE = os.getenv("E_EAGLE") or "🦅"
E_TIGER = os.getenv("E_TIGER") or "🐯"
E_R = os.getenv("E_R") or "🏅"
E_PLUS = os.getenv("E_PLUS") or "➕"
E_MINUS = os.getenv("E_MINUS") or "➖"

# --- R points values ---
R_TRADE = 15
R_PREMARKET = 15
R_BACKTEST = 25
R_VOICE_HOUR = 1
VOICE_RECONCILE_CAP = 600   # сек: максимум, который можно досчитать после рестарта
R_RESPECT_RECEIVER = 10
R_RESPECT_GIVER = 2
# Ищем по границам слов, а не подстрокой: подстрочный поиск засчитывал "помогите"
# (просьба, а не благодарность) и ловил "gg" внутри biggest/suggest.
RESPECT_PATTERNS = [
    r"\bспасибо\w*", r"\bблагодар\w*", r"\bреспект\w*", r"\brespect\w*",
    r"\bthanks?\b", r"\bthank you\b", r"\bgg\b", r"\bкрасав\w*",
    r"\bспс\b", r"\bмерси\b", r"\bвыручил\w*", r"\bсэнкс\w*",
    r"\bпомог\b", r"\bпомогла\b", r"\bпомогли\b",
]
RESPECT_RE = re.compile("|".join(RESPECT_PATTERNS), re.IGNORECASE)
RESPECT_LIMIT_PER_TARGET = 3   # макс респектов одному человеку в день
RESPECT_LIMIT_TOTAL = 10       # макс респектов всего в день от одного

# --- counters ---
TRADES_START_COUNT = 85  # стартовое число трейдов

# --- напоминание о выборе концепта (в DM) ---
# Через сколько секунд после входа слать напоминание. Данные сервера: 40 из 45
# застрявших сидят больше месяца - люди выбирают концепт сразу либо никогда,
# поэтому напоминаем рано и всего дважды.
GATE_REMINDER_STAGES = [2 * 3600, 24 * 3600]
GATE_PANEL_CHANNEL_ID = env_id("GATE_PANEL_CHANNEL_ID")   # канал choose-concept

# --- antispam ---
NEW_ACCOUNT_DAYS = 7

# --- concepts (роль -> label, emoji) ---
CONCEPTS = {
    "mltf": ("MLTF", env_id("CONCEPT_MLTF_ROLE_ID"), os.getenv("CONCEPT_MLTF_EMOJI") or "🧭"),
    "mp": ("Market Profile", env_id("CONCEPT_MP_ROLE_ID"), os.getenv("CONCEPT_MP_EMOJI") or "📊"),
    "0dte": ("0DTE", env_id("CONCEPT_0DTE_ROLE_ID"), os.getenv("CONCEPT_0DTE_EMOJI") or "⚡"),
    "orderflow": ("OrderFlow", env_id("CONCEPT_ORDERFLOW_ROLE_ID"), os.getenv("CONCEPT_ORDERFLOW_EMOJI") or "🌊"),
    "swing": ("Swing", env_id("CONCEPT_SWING_ROLE_ID"), os.getenv("CONCEPT_SWING_EMOJI") or "🏄"),
    "pa": ("Price Action", env_id("CONCEPT_PA_ROLE_ID"), os.getenv("CONCEPT_PA_EMOJI") or "🕯️"),
}

# --- concept descriptions ---
CONCEPT_DESC = {
    "mltf": ("MLTF - Multitimeframe Analysis",
             "Анализ рынка на нескольких таймфреймах одновременно: старший даёт направление и контекст, младший - точку входа. Помогает не торговать против общего движения."),
    "mp": ("Market Profile",
           "Показывает, на каких ценах рынок провёл больше всего времени, где зоны принятия и отторжения цены. Строит профиль распределения по уровням."),
    "orderflow": ("Order Flow & Volume Profile",
                  "Анализ через объёмы: где прошли крупные ордера, на каких уровнях сконцентрирован интерес. Ловишь движение по реальному потоку ордеров, а не по свечному анализу."),
    "0dte": ("0DTE - Option Flow",
             "Потоки в опционах с экспирацией в тот же день. Показывает, куда позиционируются крупные игроки прямо сейчас, даёт краткосрочные ориентиры."),
    "pa": ("Price Action - свечной анализ",
           "Чтение рынка по чистому графику: свечные паттерны, структура, уровни, без индикаторов. Основа для входов и выходов."),
    "swing": ("Swing - свинг-трейдинг",
              "Тот же price action, но для позиций, удерживаемых дольше (дни-недели), ловля крупных движений, а не внутридня."),
}

# ==================================================================
PRAGUE = ZoneInfo("Europe/Prague")
NEWYORK = ZoneInfo("America/New_York")
FF_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# data files
STATS_FILE = "voice_stats.json"
SESSIONS_FILE = "voice_sessions.json"
RCREDIT_FILE = "voice_rcredit.json"
POINTS_FILE = "points.json"
LB_STATE_FILE = "lb_state.json"
ROLE_MEMORY_FILE = "role_memory.json"
RUNTIME_FILE = "runtime_state.json"


def save_json_atomic(path, data, label=None):
    """Записать JSON через временный файл + os.replace.

    Прямая запись в целевой файл означает, что рестарт (или падение) в момент
    dump оставит обрезанный JSON и потерю всего состояния - для points.json это
    весь лидерборд. os.replace атомарен, поэтому файл на диске всегда либо
    старый целиком, либо новый целиком.
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        print(f"{label or path} save error: {e}")
        try:
            os.remove(tmp)
        except Exception:
            pass

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True
bot = discord.Bot(intents=intents, debug_guilds=[GUILD_ID] if GUILD_ID else None)


# ==================================================================
#                      POINTS (R) SYSTEM
# ==================================================================
# points structure: {uid: {"all": N, "week": N, "month": N}}
points = {}
# respect tracking per day: {"date": "YYYY-MM-DD", "given": {giver: {target: count}}, "given_total": {giver: count}}
respect_log = {"date": "", "given": {}, "total": {}}

def load_points():
    global points
    if os.path.exists(POINTS_FILE):
        try:
            with open(POINTS_FILE, "r") as f:
                raw = json.load(f)
                points = {int(k): v for k, v in raw.items()}
        except Exception as e:
            print(f"points load error: {e}")
            points = {}

def save_points():
    save_json_atomic(POINTS_FILE, {str(k): v for k, v in points.items()}, "points")

def is_no_points(member):
    if member is None or member.bot:
        return True
    role_ids = [r.id for r in member.roles]
    return any(rid in role_ids for rid in NO_POINTS_ROLE_IDS)

def add_points(member, amount):
    """add R to a member across all/week/month, unless excluded"""
    if is_no_points(member):
        return
    uid = member.id
    if uid not in points:
        points[uid] = {"all": 0, "week": 0, "month": 0}
    points[uid]["all"] += amount
    points[uid]["week"] += amount
    points[uid]["month"] += amount
    touch_seen(uid)          # нужно, чтобы находить затихших в недельной сводке
    save_points()

def add_points_by_id(uid, member_obj, amount):
    """same but when we already have member object for role check"""
    add_points(member_obj, amount)


# ==================================================================
#                      VOICE STATS
# ==================================================================
voice_join_times = {}
voice_totals = {}

def load_stats():
    global voice_totals
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                voice_totals = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            print(f"stats load error: {e}")
            voice_totals = {}

def save_stats():
    save_json_atomic(STATS_FILE, {str(k): v for k, v in voice_totals.items()}, "stats")

def load_sessions():
    global voice_join_times
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
                voice_join_times = {int(k): datetime.fromisoformat(v) for k, v in data.items()}
        except Exception as e:
            print(f"sessions load error: {e}")
            voice_join_times = {}

def save_sessions():
    save_json_atomic(SESSIONS_FILE, {str(k): v.isoformat() for k, v in voice_join_times.items()}, "sessions")

# R-кредит за войс: сколько ПОЛНЫХ часов уже конвертировано в R (переживает рестарты)
voice_rcredit = {}  # uid -> hours already awarded

def load_rcredit():
    global voice_rcredit
    if os.path.exists(RCREDIT_FILE):
        try:
            with open(RCREDIT_FILE, "r") as f:
                voice_rcredit = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            print(f"rcredit load error: {e}")
            voice_rcredit = {}
    else:
        # первый запуск после патча: исторические часы считаем уже "оплаченными",
        # чтобы не взорвать weekly/monthly лидерборды задним числом
        voice_rcredit = {uid: int(secs // 3600) for uid, secs in voice_totals.items()}
        save_rcredit()

def save_rcredit():
    save_json_atomic(RCREDIT_FILE, {str(k): v for k, v in voice_rcredit.items()}, "rcredit")

def settle_voice_r():
    """Начислить R за каждый полный час войса, накопленный суммарно (сессии складываются)."""
    now = datetime.now(timezone.utc)
    changed = False
    for uid in set(list(voice_totals.keys()) + list(voice_join_times.keys())):
        total = voice_totals.get(uid, 0)
        joined = voice_join_times.get(uid)
        if joined:
            total += (now - joined).total_seconds()
        due = int(total // 3600) - voice_rcredit.get(uid, 0)
        if due > 0:
            member = None
            for g in bot.guilds:
                member = g.get_member(uid)
                if member:
                    break
            if member is None:
                # участника нет в кэше (ещё не прогрузился или вышел) - кредит НЕ
                # списываем, иначе часы сгорят: на следующем проходе due станет 0
                # и человек уже никогда не получит эти R
                continue
            add_points(member, due * R_VOICE_HOUR)  # is_no_points отсечёт HADM/MDR/ботов
            voice_rcredit[uid] = voice_rcredit.get(uid, 0) + due
            changed = True
    if changed:
        save_rcredit()

async def reconcile_voice_on_start():
    """Закрыть сессии, открытые до рестарта, и переоткрыть их для тех, кто в войсе.

    Время режется по VOICE_RECONCILE_CAP: пока бот жив, voice_autosave обновляет
    метку каждые 5 минут, поэтому разрыв больше этого - это простой бота, а не
    время в войсе. Без ограничения падение на 12 часов дарило человеку 12 часов
    войса и 12 R.
    """
    now = datetime.now(timezone.utc)
    for uid, joined in list(voice_join_times.items()):
        secs = min((now - joined).total_seconds(), VOICE_RECONCILE_CAP)
        if secs > 0:
            voice_totals[uid] = voice_totals.get(uid, 0) + secs
    voice_join_times.clear()
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    voice_join_times[member.id] = now
    save_stats()
    save_sessions()
    settle_voice_r()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return  # музыкальные и прочие боты не копят часы
    now = datetime.now(timezone.utc)
    if before.channel is None and after.channel is not None:
        # setdefault, а не присваивание: дубль события не должен обнулять
        # уже идущую сессию и терять накопленное время
        voice_join_times.setdefault(member.id, now)
        save_sessions()
    elif before.channel is not None and after.channel is None:
        joined = voice_join_times.pop(member.id, None)
        if joined:
            secs = (now - joined).total_seconds()
            voice_totals[member.id] = voice_totals.get(member.id, 0) + secs
            save_stats()
            settle_voice_r()
            save_sessions()

def fmt_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h} ч {m} мин"
    return f"{m} мин"


# ==================================================================
#                      CONCEPT PANEL
# ==================================================================
CONCEPT_ROLE_IDS = {role_id for (_, role_id, _) in CONCEPTS.values()}

# статусные роли, снятые при уходе в choose-concept: {uid: [role_id, ...]}
# нужно, чтобы вернуть человеку Member/Legend после повторного выбора концепта
role_memory = {}

def load_role_memory():
    global role_memory
    if os.path.exists(ROLE_MEMORY_FILE):
        try:
            with open(ROLE_MEMORY_FILE, "r") as f:
                role_memory = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            print(f"role memory load error: {e}")
            role_memory = {}

def save_role_memory():
    save_json_atomic(ROLE_MEMORY_FILE, {str(k): v for k, v in role_memory.items()}, "role memory")

# id тех, чьи роли прямо сейчас меняет сам бот - чтобы on_member_update
# не реагировал на собственные правки и не откатывал их
_bot_role_edits = set()

def mark_bot_edit(uid):
    """Пометить участника как «правит бот» на несколько секунд.

    Событие on_member_update приходит уже после ответа API, поэтому снимаем
    метку по таймеру, а не сразу после вызова.
    """
    _bot_role_edits.add(uid)
    async def clear():
        await asyncio.sleep(5)
        _bot_role_edits.discard(uid)
    asyncio.create_task(clear())

def has_concept(member):
    return any(r.id in CONCEPT_ROLE_IDS for r in member.roles)

def is_gate_exempt(member):
    return any(r.id in GATE_EXEMPT_ROLE_IDS for r in member.roles)


def is_service(member):
    """Служебный аккаунт: в счётчиках и рассылках не участвует."""
    return any(r.id == SERVICE_ROLE_ID for r in member.roles)

async def send_to_gate(member, drop_concept=None, reason="нет ни одного концепта"):
    """Снять статусные роли (запомнив их) и вернуть choose-concept.

    Снимаем именно все статусные роли: в Discord allow-оверрайд любой роли
    перебивает deny у choose-concept, поэтому с Member на руках человек
    продолжал бы видеть сервер и гейт был бы декоративным.
    """
    guild = member.guild
    gate = guild.get_role(GATE_ROLE_ID)
    had = [guild.get_role(rid) for rid in STATUS_ROLE_IDS]
    had = [r for r in had if r and r in member.roles]

    role_memory[member.id] = [r.id for r in had]
    save_role_memory()

    to_remove = list(had)
    if drop_concept is not None:
        to_remove.append(drop_concept)

    mark_bot_edit(member.id)
    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason=reason)
        if gate and gate not in member.roles:
            await member.add_roles(gate, reason=reason)
    except Exception as e:
        print(f"gate lock error for {member.id}: {e}")

async def restore_from_gate(member, concept=None):
    """Снять choose-concept и вернуть запомненный статус.

    concept передаётся при нажатии кнопки; при ручной выдаче концепта админом
    роль уже на человеке и добавлять её не нужно.
    """
    guild = member.guild
    gate = guild.get_role(GATE_ROLE_ID)
    remembered = role_memory.pop(member.id, None)
    save_role_memory()

    to_add = [concept] if concept is not None else []
    if remembered:
        for rid in remembered:
            r = guild.get_role(rid)
            if r and r not in member.roles:
                to_add.append(r)
    elif not any(r.id in (NEWBIE_ROLE_ID, MEMBER_ROLE_ID) for r in member.roles):
        # первый выбор концепта - выдаём базовый доступ
        newbie = guild.get_role(NEWBIE_ROLE_ID)
        if newbie:
            to_add.append(newbie)

    mark_bot_edit(member.id)
    try:
        if to_add:
            await member.add_roles(*to_add, reason="выбран концепт")
        if gate and gate in member.roles:
            await member.remove_roles(gate, reason="выбран концепт")
            bump_week("gate_passed")
    except Exception as e:
        print(f"gate unlock error for {member.id}: {e}")


class ConceptButton(discord.ui.Button):
    def __init__(self, key, label, role_id, emoji=None):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f"concept_{key}", emoji=emoji)
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild
        concept = guild.get_role(self.role_id)
        if concept is None:
            await interaction.response.send_message("Роль концепта не найдена, напиши админу", ephemeral=True)
            return

        if concept in member.roles:
            others = [r for r in member.roles if r.id in CONCEPT_ROLE_IDS and r.id != concept.id]
            if not others and not is_gate_exempt(member):
                await send_to_gate(member, drop_concept=concept)
                await interaction.response.send_message(
                    f"Роль {concept.name} снята. Это был твой последний концепт, "
                    "поэтому доступ к серверу закрыт - выбери концепт, который торгуешь, "
                    "чтобы вернуться 🔒",
                    ephemeral=True)
                return
            await member.remove_roles(concept, reason="снят концепт")
            await interaction.response.send_message(f"Роль {concept.name} снята", ephemeral=True)
            return

        await restore_from_gate(member, concept)
        await interaction.response.send_message(f"Выдано: {concept.name}. Сервер открыт 🔓", ephemeral=True)

class ConceptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, (label, role_id, emoji) in CONCEPTS.items():
            self.add_item(ConceptButton(key, label, role_id, emoji))


# ==================================================================
#                  CONCEPT DESCRIPTION PANEL
# ==================================================================
class ConceptDescButton(discord.ui.Button):
    def __init__(self, key, label, emoji=None):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f"desc_{key}", emoji=emoji)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        title, desc = CONCEPT_DESC.get(self.key, ("?", "Описание не найдено"))
        embed = discord.Embed(title=title, description=desc, color=0xd7ecff)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ConceptDescView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # use same emoji/labels as concepts but map to descriptions
        order = [("mltf", "MLTF"), ("mp", "Market Profile"), ("orderflow", "Order Flow"),
                 ("0dte", "0DTE"), ("pa", "Price Action"), ("swing", "Swing")]
        emoji_map = {k: v[2] for k, v in CONCEPTS.items()}
        for key, label in order:
            self.add_item(ConceptDescButton(key, label, emoji_map.get(key)))


# ==================================================================
#                      NEWS PANEL
# ==================================================================
class NewsButton(discord.ui.Button):
    def __init__(self, key, label, emoji):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f"news_{key}", emoji=emoji)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        role_map = {"red": NEWS_RED_ROLE_ID, "orange": NEWS_ORANGE_ROLE_ID, "geo": NEWS_GEO_ROLE_ID}
        role = interaction.guild.get_role(role_map[self.key])
        member = interaction.user
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"Пинги {role.name} выключены", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"Пинги {role.name} включены 🔔", ephemeral=True)

class NewsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NewsButton("red", "News Red", "🔴"))
        self.add_item(NewsButton("orange", "News Orange", "🟠"))
        self.add_item(NewsButton("geo", "NewsGeo", "🌍"))


# ==================================================================
#                      TICKETS
# ==================================================================
TICKET_OWNER_TAG = "ticket-owner:"
_closing_tickets = set()   # каналы, которые прямо сейчас закрываются


def ticket_channel_name(user):
    """Имя канала так, как его всё равно нормализует Discord.

    Discord приводит имя к нижнему регистру и заменяет пробелы/спецсимволы на
    дефисы. Раньше искали по сырому нику, поэтому ник вида "Иван Петров" не
    находил канал ticket-иван-петров, и человек мог открыть сколько угодно тикетов.
    """
    base = re.sub(r"[^\w-]+", "-", user.name.lower(), flags=re.UNICODE).strip("-")
    return f"ticket-{base or user.id}"[:95]


def find_open_ticket(category, user):
    """Ищем тикет по владельцу в topic, с откатом на имя для старых каналов."""
    tag = f"{TICKET_OWNER_TAG}{user.id}"
    for ch in category.text_channels:
        if ch.topic and tag in ch.topic:
            return ch
    return discord.utils.get(category.text_channels, name=ticket_channel_name(user))


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create a ticket", style=discord.ButtonStyle.secondary, custom_id="ticket_open", emoji="📩")
    async def open_ticket(self, button, interaction):
        guild = interaction.guild
        author = interaction.user
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message("Категория тикетов не найдена, скажи админу", ephemeral=True)
            return
        existing = find_open_ticket(category, author)
        if existing:
            await interaction.response.send_message(f"У тебя уже открыт тикет: {existing.mention}", ephemeral=True)
            return
        admin_role = guild.get_role(ADMIN_ROLE_ID)
        moder_role = guild.get_role(MODER_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if moder_role:
            overwrites[moder_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        ch = await category.create_text_channel(
            name=ticket_channel_name(author),
            topic=f"{TICKET_OWNER_TAG}{author.id}",
            overwrites=overwrites)
        embed = discord.Embed(
            title="🎫 Ticket Opened",
            description=(
                f"{author.mention}, welcome to your private ticket.\n"
                f"*{author.mention}, добро пожаловать в твой приватный тикет.*\n\n"
                "**Describe your issue** - trading question, account access, or technical problem.\n"
                "*Опиши свою проблему - вопрос по трейдингу, доступ к аккаунту или техническая проблема.*\n\n"
                "A team member will respond as soon as possible.\n"
                "*Участник команды ответит как можно скорее.*"
            ),
            color=0xd7ecff,
        )
        embed.set_footer(text="laurus", icon_url=BRAND_ICON_URL)
        await ch.send(content=author.mention, embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"Ticket created: {ch.mention}", ephemeral=True)

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary, custom_id="ticket_claim", emoji="🙋")
    async def claim_ticket(self, button, interaction):
        staff = interaction.user
        role_ids = [r.id for r in staff.roles]
        if not any(rid in role_ids for rid in (ADMIN_ROLE_ID, MODER_ROLE_ID)):
            await interaction.response.send_message("Только команда может брать тикеты.", ephemeral=True)
            return
        embed = discord.Embed(description=f"🙋 Ticket claimed by {staff.mention}\n*Тикет взят: {staff.mention}*", color=0xd7ecff)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.secondary, custom_id="ticket_close", emoji="🔒")
    async def close_ticket(self, button, interaction):
        global tickets_solved
        # без этого повторные клики накручивают счётчик решённых тикетов
        # и вторым заходом пытаются удалить уже удалённый канал
        if interaction.channel.id in _closing_tickets:
            await interaction.response.send_message("Тикет уже закрывается", ephemeral=True)
            return
        _closing_tickets.add(interaction.channel.id)
        await interaction.response.send_message("Saving transcript & closing in 5s... / Сохраняю историю и закрываю через 5 сек...", ephemeral=False)
        # build transcript
        try:
            lines = []
            async for msg in interaction.channel.history(limit=500, oldest_first=True):
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                content = msg.content or ""
                for emb in msg.embeds:
                    if emb.description:
                        content += f" [embed: {emb.description[:100]}]"
                lines.append(f"[{ts}] {msg.author.name}: {content}")
            transcript = "\n".join(lines) if lines else "(пусто)"
            # имя файла собираем сами, а не из имени канала: полагаться на то, что
            # Discord вычистит слеши, для пути в файловой системе неправильно.
            # И пишем во временную папку, а не в каталог бота
            safe = re.sub(r"[^\w-]+", "-", interaction.channel.name)[:60] or "ticket"
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt",
                                             delete=False) as f:
                f.write(transcript)
                fname = f.name
            try:
                log_ch = bot.get_channel(TRANSCRIPT_CHANNEL_ID) or bot.get_channel(ADMIN_LOG_CHANNEL_ID)
                if log_ch:
                    await log_ch.send(
                        content=f"📄 Transcript: {interaction.channel.name}",
                        file=discord.File(fname, filename=f"transcript-{safe}.txt"),
                    )
            finally:
                os.remove(fname)
        except Exception as e:
            print(f"transcript error: {e}")
        # auto-count ticket as solved
        tickets_solved += 1
        save_lb_state()
        await update_counter_channels()
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except Exception as e:
            # не смогли удалить - снимаем блокировку, иначе тикет нельзя закрыть
            # уже никогда: канал остался, а повторный клик отбивается
            _closing_tickets.discard(interaction.channel.id)
            print(f"[ticket] не удалось удалить канал: {e}")


# ==================================================================
#                      STATS PANEL
# ==================================================================
class StatsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Моя карта", style=discord.ButtonStyle.secondary, custom_id="stats_card", emoji="🎴")
    async def show_card(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            img = await build_trader_card(interaction.user)
            await interaction.followup.send(
                "Карта собирается из твоих реальных цифр: заявки /trade, серии, войс. "
                "Больше закрытых заявок - интереснее арт и титул.",
                file=discord.File(img, "card.png"), ephemeral=True)
            return
        except Exception as e:
            print(f"[card] рендер не удался: {e}")
        embed, n = card_embed(interaction.user)
        if embed is None:
            await interaction.followup.send(
                f"Закрытых заявок: {n}. Заяви сделку командой /trade и закрой её, "
                f"когда выйдешь - каждая закрытая идёт в карту.", ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Моя статистика", style=discord.ButtonStyle.secondary, custom_id="stats_show", emoji="📊")
    async def show_stats(self, button, interaction):
        member = interaction.user
        guild = interaction.guild
        joined = member.joined_at
        days = (datetime.now(timezone.utc) - joined).days if joined else 0
        my_concepts = [label for key, (label, rid, e) in CONCEPTS.items() if guild.get_role(rid) in member.roles]
        subs = []
        if guild.get_role(NEWS_RED_ROLE_ID) in member.roles:
            subs.append("🔴 Red")
        if guild.get_role(NEWS_ORANGE_ROLE_ID) in member.roles:
            subs.append("🟠 Orange")
        if guild.get_role(NEWS_GEO_ROLE_ID) in member.roles:
            subs.append("🌍 Geo")
        voice_secs = voice_totals.get(member.id, 0)
        if member.id in voice_join_times:
            voice_secs += (datetime.now(timezone.utc) - voice_join_times[member.id]).total_seconds()
        p = points.get(member.id, {"all": 0, "week": 0, "month": 0})

        embed = discord.Embed(title=f"Статистика - {member.display_name}", color=0xd7ecff)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📅 На сервере", value=f"{days} дн.", inline=True)
        vplace = ""
        if voice_secs > 60:
            vall = sorted(voice_totals.values(), reverse=True)
            vplace = f" · #{1 + sum(1 for v in vall if v > voice_secs)} по серверу"
        embed.add_field(name="🎙 Время в войсе",
                        value=f"{fmt_duration(voice_secs)}{vplace}", inline=True)
        earners = sorted((v.get("all", 0) for v in points.values()
                          if v.get("all", 0) > 0), reverse=True)
        rank_line = ""
        if p["all"] > 0 and earners:
            place = 1 + sum(1 for e in earners if e > p["all"])
            rank_line = f"\nМесто по заработанному: **#{place}** из {len(earners)}"
        bal = balance(member.id)
        prices = sorted({it["price"] for it in SHOP_ITEMS.values()})
        nxt = next((pr for pr in prices if pr > bal), None)
        if bal >= prices[0]:
            afford = sum(1 for it in SHOP_ITEMS.values() if it["price"] <= bal)
            goal = (f"\n🛒 Хватает на {afford} "
                    f"{plural(afford, 'товар', 'товара', 'товаров')} в магазине")
            if nxt:
                goal += f" · до следующего {nxt - bal} R"
        else:
            goal = f"\n🛒 До первой покупки {prices[0] - bal} R"
        embed.add_field(name=f"{E_R} Очки R",
                        value=f"Заработано: {p['all']} | Неделя: {p['week']} | Месяц: {p['month']}\n"
                              f"Баланс к трате: **{bal}**{rank_line}{goal}", inline=False)
        streak = streak_line(member.id)
        rec = session_state.get(str(member.id), {})
        if streak or rec.get("total"):
            val = streak or "серия прервана"
            if rec.get("best"):
                val += f" · рекорд {rec['best']}"
            if rec.get("total"):
                val += f" · всего открытий {rec['total']}"
            nxt_ms = next((k for k in sorted(SESSION_STREAK_BONUS)
                           if k > rec.get("streak", 0)), None)
            if nxt_ms and rec.get("streak", 0) > 0:
                val += (f"\nДо бонуса +{SESSION_STREAK_BONUS[nxt_ms]} R: "
                        f"ещё {nxt_ms - rec['streak']} "
                        f"{plural(nxt_ms - rec['streak'], 'день', 'дня', 'дней')}")
            embed.add_field(name="🔔 Открытия сессии", value=val, inline=False)
        my_recs = declared_records(uid=member.id)
        if my_recs:
            tot = sum(r["result_r"] for r in my_recs)
            best = max(r["result_r"] for r in my_recs)
            embed.add_field(
                name="📈 Заявки /trade",
                value=f"{len(my_recs)} {plural(len(my_recs), 'закрытая', 'закрытые', 'закрытых')} · "
                      f"итог **{tot:+.2f}R** · лучшая {best:+.1f}R · карта - кнопкой ниже 🎴",
                inline=False)
        badges = []
        if voice_secs >= 10 * 3600:
            badges.append("🎙 10ч+ войса")
        if rec.get("streak", 0) >= 3:
            badges.append(f"🔥 серия {rec['streak']}")
        if len(my_recs) >= 5:
            badges.append("📊 5+ заявок")
        elif my_recs:
            badges.append("📈 первая заявка")
        if p["all"] >= 100:
            badges.append("💎 100+ R")
        if p.get("spent", 0) > 0:
            badges.append("🛒 покупатель")
        if badges:
            embed.add_field(name="Значки", value=" · ".join(badges), inline=False)
        embed.add_field(name="📊 Концепты", value=", ".join(my_concepts) if my_concepts else "нет", inline=False)
        embed.add_field(name="🔔 Подписки", value=", ".join(subs) if subs else "нет", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)



def loop_guard(name):
    """Не дать tasks.loop умереть насовсем от разовой ошибки.

    Восстановимыми py-cord считает только OSError/ConnectionClosed/ClientError/
    TimeoutError. Любое другое исключение - в том числе обычный HTTPException
    при 5xx от Discord или Forbidden - останавливает цикл навсегда: процесс
    остаётся online, а новости/лидерборд молча перестают работать до ручного
    рестарта. Проверено: без защиты цикл умирает со второго тика.
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                await fn(*args, **kwargs)
            except Exception as e:
                print(f"[loop:{name}] {type(e).__name__}: {e}")
                traceback.print_exc()
        return wrapper
    return deco

# ==================================================================
#                    FOREXFACTORY NEWS
# ==================================================================
feed_cache = []
feed_fetched_at = None
# дедуп-ключи хранятся как {ключ: время добавления} и переживают рестарт,
# иначе перезапуск у границы окна повторно пингует роль по той же новости
posted_alerts = {}
posted_results = {}
last_digest_day = None
# сколько напоминаний о концепте уже отправлено: {uid: 0..len(GATE_REMINDER_STAGES)}
gate_reminders = {}
gate_reminders_seeded = False
# Отметки «за этот период уже публиковали». Держать их только в памяти нельзя:
# рестарт внутри окна повторяет публикацию - именно так задвоился бриф сессии.
once_marks = {}     # "echo_day" / "blind_week" / "raid_alert" -> значение


def mark_dedup(store, key):
    store[str(key)] = datetime.now(timezone.utc).isoformat()
    save_runtime_state()


def prune_dedup(store, days=7):
    """Выкинуть записи старше N дней, иначе словари растут без предела."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for k in [k for k, ts in list(store.items()) if _ts_before(ts, cutoff)]:
        store.pop(k, None)


def _ts_before(ts, cutoff):
    try:
        return datetime.fromisoformat(ts) < cutoff
    except Exception:
        return True  # мусорная запись - тоже под нож


def load_runtime_state():
    """respect_log и дедупы новостей/событий, переживающие рестарт."""
    global respect_log, posted_alerts, posted_results, reminded_events, last_digest_day
    global gate_reminders, gate_reminders_seeded, week_stats, echoed_threads
    if not os.path.exists(RUNTIME_FILE):
        return
    try:
        with open(RUNTIME_FILE, "r") as f:
            data = json.load(f)
        respect_log = data.get("respect_log", respect_log)
        posted_alerts = data.get("posted_alerts", {})
        posted_results = data.get("posted_results", {})
        reminded_events = data.get("reminded_events", {})
        day = data.get("last_digest_day")
        last_digest_day = datetime.fromisoformat(day).date() if day else None
        gate_reminders = data.get("gate_reminders", {})
        gate_reminders_seeded = data.get("gate_reminders_seeded", False)
        once_marks.update(data.get("once_marks", {}))
        week_stats.update(data.get("week_stats", {}))
        echoed_threads.update(data.get("echoed_threads", {}))
        for store in (posted_alerts, posted_results, reminded_events):
            prune_dedup(store)
    except Exception as e:
        print(f"runtime state load error: {e}")


def save_runtime_state():
    save_json_atomic(RUNTIME_FILE, {
        "respect_log": respect_log,
        "posted_alerts": posted_alerts,
        "posted_results": posted_results,
        "reminded_events": reminded_events,
        "last_digest_day": last_digest_day.isoformat() if last_digest_day else None,
        "gate_reminders": gate_reminders,
        "gate_reminders_seeded": gate_reminders_seeded,
        "once_marks": once_marks,
        "week_stats": week_stats,
        "echoed_threads": echoed_threads,
    }, "runtime state")

async def fetch_feed():
    global feed_cache, feed_fetched_at
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async with session.get(FF_FEED, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    feed_cache = await resp.json(content_type=None)
                    feed_fetched_at = datetime.now(PRAGUE)
                    print(f"FF feed: {len(feed_cache)} events")
    except Exception as e:
        print(f"FF feed error: {e}")

def all_usd_today():
    """all USD events today incl. Holiday for bank-holiday note"""
    now = datetime.now(PRAGUE)
    out = []
    for ev in feed_cache:
        try:
            if ev.get("country") != "USD":
                continue
            dt = datetime.fromisoformat(ev["date"]).astimezone(PRAGUE)
            if dt.date() == now.date():
                out.append(ev)
        except Exception:
            continue
    return out

def usd_events():
    out = []
    for ev in feed_cache:
        try:
            if ev.get("country") != "USD":
                continue
            impact = ev.get("impact", "")
            if impact not in ("High", "Medium"):
                continue
            dt = datetime.fromisoformat(ev["date"]).astimezone(PRAGUE)
            dt_ny = dt.astimezone(NEWYORK)
            out.append({"title": ev.get("title", "?"), "impact": impact, "dt": dt, "dt_ny": dt_ny,
                        "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""),
                        "actual": ev.get("actual", "")})
        except Exception:
            continue
    return out

def impact_emoji(impact):
    return "🔴" if impact == "High" else "🟠"

def result_comment(actual, forecast):
    """simple neutral comment: beat / miss / inline"""
    try:
        a = float(str(actual).replace("%", "").replace("K", "").replace("M", "").replace(",", "."))
        f = float(str(forecast).replace("%", "").replace("K", "").replace("M", "").replace(",", "."))
        if a > f:
            return "выше прогноза"
        elif a < f:
            return "ниже прогноза"
        else:
            return "по прогнозу"
    except Exception:
        return None

@tasks.loop(minutes=1)
@loop_guard("news")
async def news_loop():
    global last_digest_day
    now = datetime.now(PRAGUE)
    if feed_fetched_at is None or (now - feed_fetched_at) > timedelta(hours=1):
        await fetch_feed()
    channel = bot.get_channel(NEWS_CHANNEL_ID)
    if channel is None:
        return
    events = usd_events()
    allowed = discord.AllowedMentions(roles=True)

    # ---- morning digest ----
    # Окно, а не ровно :00 - иначе рестарт в 8:00 съедал бы дайджест на весь день.
    # Но именно окно, а не "час уже наступил": иначе первый запуск с пустым
    # last_digest_day шлёт "новости на сегодня" хоть в полночь.
    if DIGEST_HOUR <= now.hour < DIGEST_HOUR + DIGEST_WINDOW_HOURS and last_digest_day != now.date():
        last_digest_day = now.date()
        save_runtime_state()
        todays = [e for e in events if e["dt"].date() == now.date()]
        # bank holiday note
        holidays = [ev for ev in all_usd_today() if ev.get("impact") == "Holiday" or "holiday" in ev.get("title", "").lower()]
        embed = discord.Embed(title=f"📰 Новости на сегодня - {now.strftime('%d.%m.%Y')}", color=0xd7ecff)
        if todays:
            todays.sort(key=lambda e: e["dt"])
            for e in todays:
                embed.add_field(name=f"{impact_emoji(e['impact'])} {e['dt_ny']:%H:%M} NY · {e['dt']:%H:%M} EU - {e['title']}",
                                value=f"Forecast: {e['forecast'] or '-'} | Previous: {e['previous'] or '-'}", inline=False)
        else:
            embed.description = "Сегодня нет USD-новостей высокой/средней важности."
        if holidays:
            names = ", ".join(h.get("title", "Holiday") for h in holidays)
            embed.add_field(name="🏦 Bank Holiday", value=f"Сегодня: {names}. Рынки могут быть тонкими.", inline=False)
        pings = []
        if any(e["impact"] == "High" for e in todays):
            pings.append(f"<@&{NEWS_RED_ROLE_ID}>")
        if any(e["impact"] == "Medium" for e in todays):
            pings.append(f"<@&{NEWS_ORANGE_ROLE_ID}>")
        await channel.send(content=" ".join(pings), embed=embed, allowed_mentions=allowed)

    # ---- alerts before event ----
    # События группируем по времени выхода. В 14:00 их бывает четыре сразу, и
    # раньше выходило четыре пинга и четыре ставки на одно и то же движение
    # рынка - с четырьмя одинаковыми итогами. Реакция-то одна.
    due = {}
    for e in events:
        delta = (e["dt"] - now).total_seconds() / 60
        if ALERT_MINUTES - 1 < delta <= ALERT_MINUTES:
            due.setdefault(e["dt"], []).append(e)

    for dt, group in due.items():
        key = "|".join(sorted(x["title"] for x in group)) + f"|{dt.isoformat()}"
        if key in posted_alerts:
            continue
        mark_dedup(posted_alerts, key)
        group.sort(key=lambda x: 0 if x["impact"] == "High" else 1)
        top = group[0]
        role_id = NEWS_RED_ROLE_ID if any(x["impact"] == "High" for x in group) else NEWS_ORANGE_ROLE_ID
        color = 0xff4444 if any(x["impact"] == "High" for x in group) else 0xffaa33

        if len(group) == 1:
            title = f"{impact_emoji(top['impact'])} Через {ALERT_MINUTES} минут: {top['title']}"
            body = f"Forecast: {top['forecast'] or '-'} | Previous: {top['previous'] or '-'}"
        else:
            title = f"{impact_emoji(top['impact'])} Через {ALERT_MINUTES} минут: {len(group)} выхода сразу"
            body = "\n".join(
                f"{impact_emoji(x['impact'])} {x['title']}"
                + (f" · прогноз {x['forecast']}" if x["forecast"] else "")
                for x in group)
        embed = discord.Embed(
            title=title,
            description=f"🕐 {top['dt_ny']:%H:%M} NY · {top['dt']:%H:%M} EU\n{body}",
            color=color)
        embed.add_field(
            name="🎲 Ставка на реакцию",
            value=f"Куда уйдёт **{BET_INSTRUMENT_NAME}** за {BET_REACTION_MIN} минут "
                  f"после выхода?\nНоминалы: {', '.join(str(s) for s in BET_STAKES)} {E_R}. "
                  f"Одна ставка.",
            inline=False)
        msg = await channel.send(content=f"<@&{role_id}>", embed=embed,
                                 allowed_mentions=allowed, view=BetView())
        open_bets[str(msg.id)] = {
            "key": key,
            "title": top["title"] if len(group) == 1 else f"{len(group)} выхода в {top['dt']:%H:%M}",
            "forecast": top["forecast"],
            "dt": dt.astimezone(timezone.utc).isoformat(),
            "channel_id": channel.id, "bets": {}, "settled": False}
        save_bets()

    # Блок «итог новости по фактическому значению» удалён: фид ForexFactory не
    # отдаёт поле actual вообще (проверено на 17 прошедших событиях - пусто у
    # всех), поэтому за полтора месяца не вышло ни одного такого поста. Итог
    # теперь публикует bet_settle_loop по реакции рынка, и он же считает ставки.


# ==================================================================
#                    EVENT REMINDERS
# ==================================================================
reminded_events = {}
EVENT_IGNORE = ["MorgenCALL"]
EVENT_REMINDER_MINUTES = 60

@tasks.loop(minutes=1)
@loop_guard("events")
async def event_loop():
    now = datetime.now(timezone.utc)
    for guild in bot.guilds:
        try:
            events = await guild.fetch_scheduled_events()
        except Exception:
            continue
        for ev in events:
            if any(ig.lower() in ev.name.lower() for ig in EVENT_IGNORE):
                continue
            if ev.start_time is None or str(ev.id) in reminded_events:
                continue
            delta = (ev.start_time - now).total_seconds() / 60
            if EVENT_REMINDER_MINUTES - 1 < delta <= EVENT_REMINDER_MINUTES:
                mark_dedup(reminded_events, ev.id)
                channel = bot.get_channel(NEWS_CHANNEL_ID) or bot.get_channel(ADMIN_LOG_CHANNEL_ID)
                if channel:
                    pings = f"<@&{NEWBIE_ROLE_ID}> <@&{MEMBER_ROLE_ID}>"
                    embed = discord.Embed(title=f"⏰ Через час: {ev.name}",
                                          description=ev.description or "Заходи, будет полезно.",
                                          color=0xd7ecff)
                    await channel.send(content=pings, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))


# ==================================================================
#              REACTIONS + R FOR FORUM POSTS
# ==================================================================
trades_counter = TRADES_START_COUNT

async def get_starter(thread):
    starter = None
    async for msg in thread.history(limit=1, oldest_first=True):
        starter = msg
        break
    if starter is None:
        starter = thread.starting_message
    return starter

@bot.event
async def on_thread_create(thread):
    parent_id = thread.parent_id
    starter = None

    # reactions + counter update
    if parent_id in (TEAM_TRADES_CHANNEL_ID, USER_TRADES_CHANNEL_ID):
        try:
            await asyncio.sleep(2)  # give Discord a moment to attach starter message
            starter = await get_starter(thread)
            if starter:
                if parent_id == TEAM_TRADES_CHANNEL_ID:
                    await starter.add_reaction(E_EAGLE)
                else:
                    await starter.add_reaction(E_PLUS)
                    await starter.add_reaction(E_MINUS)
            if _trades_cache["value"] is not None:
                _trades_cache["value"] += 1  # дешевле, чем перечитывать весь архив
            await update_counter_channels()
        except Exception as e:
            print(f"forum reaction error: {e}")

    # R points for post author
    author = getattr(thread, "owner", None)
    if author is None:
        try:
            if starter is None:
                starter = await get_starter(thread)
            author = starter.author if starter else None
        except Exception:
            author = None
    if author and not author.bot:
        member = thread.guild.get_member(author.id)
        if member:
            if parent_id in (TEAM_TRADES_CHANNEL_ID, USER_TRADES_CHANNEL_ID):
                add_points(member, R_TRADE)
            elif parent_id == PREMARKETS_CHANNEL_ID:
                add_points(member, R_PREMARKET)
            elif parent_id == BACKTESTS_CHANNEL_ID:
                add_points(member, R_BACKTEST)


# ==================================================================
#              RESPECT SYSTEM (reply + thank words)
# ==================================================================
def reset_respect_if_new_day():
    today = datetime.now(PRAGUE).strftime("%Y-%m-%d")
    if respect_log["date"] != today:
        respect_log["date"] = today
        respect_log["given"] = {}
        respect_log["total"] = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # respect via reply
    if message.reference and message.reference.message_id:
        low = message.content.lower()
        if RESPECT_RE.search(low):
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                ref = None
            if ref and not ref.author.bot and ref.author.id != message.author.id:
                reset_respect_if_new_day()
                giver = message.author.id
                target = ref.author.id
                given = respect_log["given"].setdefault(str(giver), {})
                total = respect_log["total"].get(str(giver), 0)
                to_target = given.get(str(target), 0)
                if total < RESPECT_LIMIT_TOTAL and to_target < RESPECT_LIMIT_PER_TARGET:
                    given[str(target)] = to_target + 1
                    respect_log["total"][str(giver)] = total + 1
                    save_runtime_state()  # иначе рестарт обнуляет дневные лимиты
                    target_member = message.guild.get_member(target)
                    giver_member = message.guild.get_member(giver)
                    if target_member:
                        add_points(target_member, R_RESPECT_RECEIVER)
                    if giver_member:
                        add_points(giver_member, R_RESPECT_GIVER)
                    try:
                        await message.add_reaction(E_R)
                    except Exception:
                        pass


# ==================================================================
#              MEMBER JOIN / LEAVE + INVITE TRACKING
# ==================================================================
invite_cache = {}  # guild_id -> {invite_code: uses}

async def cache_invites():
    for guild in bot.guilds:
        try:
            invs = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            try:
                v = await guild.vanity_invite()
                if v is not None:
                    invite_cache[guild.id]["__vanity__"] = v.uses or 0
            except Exception:
                pass
        except Exception as e:
            print(f"invite cache error: {e}")

@bot.event
async def on_invite_create(invite):
    try:
        invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses
        ch = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
        if ch:
            inviter = invite.inviter.mention if invite.inviter else "?"
            embed = discord.Embed(description=f"🔗 Новый инвайт создан: `{invite.code}` от {inviter}", color=0x5865f2)
            await ch.send(embed=embed)
    except Exception as e:
        print(f"invite create error: {e}")

@bot.event
async def on_invite_delete(invite):
    try:
        invite_cache.get(invite.guild.id, {}).pop(invite.code, None)
    except Exception:
        pass

@bot.event
async def on_member_update(before, after):
    """Держит Newbie/Member/концепты согласованными при ручных правках админа."""
    if after.bot or after.id in _bot_role_edits:
        return
    before_ids = {r.id for r in before.roles}
    after_ids = {r.id for r in after.roles}
    if before_ids == after_ids:
        return  # менялся ник/таймаут/что угодно кроме ролей

    gained = after_ids - before_ids
    lost = before_ids - after_ids
    guild = after.guild

    # сняли последний концепт руками - запираем так же, как при снятии кнопкой
    if (lost & CONCEPT_ROLE_IDS and not has_concept(after)
            and not is_gate_exempt(after) and GATE_ROLE_ID not in after_ids):
        await send_to_gate(after, reason="снят последний концепт")
        return

    # концепт выдали руками, пока человек сидел в гейте - открываем сервер
    if gained & CONCEPT_ROLE_IDS and GATE_ROLE_ID in after_ids:
        await restore_from_gate(after)
        return

    # админ выдал Member - Newbie больше не нужен, роли взаимоисключающие
    if MEMBER_ROLE_ID in gained and NEWBIE_ROLE_ID in after_ids:
        newbie = guild.get_role(NEWBIE_ROLE_ID)
        mark_bot_edit(after.id)
        try:
            await after.remove_roles(newbie, reason="выдан Member")
        except Exception as e:
            print(f"role sync error for {after.id}: {e}")
        return

    # админ снял Member - нельзя оставить человека вообще без доступа
    if MEMBER_ROLE_ID in lost and NEWBIE_ROLE_ID not in after_ids and not is_gate_exempt(after):
        if has_concept(after):
            newbie = guild.get_role(NEWBIE_ROLE_ID)
            mark_bot_edit(after.id)
            try:
                await after.add_roles(newbie, reason="снят Member")
            except Exception as e:
                print(f"role sync error for {after.id}: {e}")
        elif GATE_ROLE_ID not in after_ids:
            await send_to_gate(after, reason="снят Member, концепт не выбран")

@bot.event
async def on_member_join(member):
    bump_week("joins")
    await note_join_and_check(member)
    gate = member.guild.get_role(GATE_ROLE_ID)
    if gate:
        try:
            await member.add_roles(gate)
        except Exception as e:
            print(f"join role error: {e}")

    # figure out which invite was used
    used_code = None
    inviter = None
    vanity_used = False
    one_time = False
    try:
        before = invite_cache.get(member.guild.id, {})
        current = await member.guild.invites()
        for inv in current:
            if inv.code in before and inv.uses > before[inv.code]:
                used_code = inv.code
                inviter = inv.inviter
                break
        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in current}
        if used_code is None:
            # одноразовый инвайт исчезает сразу после использования
            gone = [c for c in before.keys()
                    if c != "__vanity__" and c not in {i.code for i in current}]
            if len(gone) == 1:
                used_code = gone[0]
                one_time = True
        if used_code is None:
            # общий (vanity) инвайт сервера не приходит в guild.invites()
            try:
                v = await member.guild.vanity_invite()
                if v is not None:
                    if (v.uses or 0) > before.get("__vanity__", 0):
                        vanity_used = True
                    invite_cache[member.guild.id]["__vanity__"] = v.uses or 0
            except Exception:
                pass
    except Exception as e:
        print(f"invite match error: {e}")

    channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(description=f"🟢 Long opened - {member.mention}", color=0x57f287)
        embed.set_thumbnail(url=member.display_avatar.url)
        acct_age = (datetime.now(timezone.utc) - member.created_at).days
        if acct_age < NEW_ACCOUNT_DAYS:
            embed.add_field(name="⚠️ Новый аккаунт", value=f"Создан {acct_age} дн. назад", inline=False)
            embed.color = 0xffaa33
        if used_code:
            inv_by = inviter.mention if inviter else "?"
            tail = " (одноразовый, истёк)" if one_time else ""
            embed.add_field(name="🔗 Инвайт", value=f"по `{used_code}` от {inv_by}{tail}", inline=False)
        elif vanity_used:
            embed.add_field(name="🔗 Инвайт", value="Общий инвайт сервера (vanity)", inline=False)
        else:
            embed.add_field(name="🔗 Инвайт", value="не определён (discovery/виджет)", inline=False)
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    bump_week("leaves")
    channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(description=f"🔴 Rugpulled - {member.name}", color=0xed4245)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)


# ==================================================================
#                    COUNTER CHANNELS
# ==================================================================
# these are voice channels whose NAME the bot updates
MEMBERS_COUNTER_ID = env_id("MEMBERS_COUNTER_ID")   # ВСТАВЬ ID канала-счётчика Members (voice channel)
TRADES_COUNTER_ID = env_id("TRADES_COUNTER_ID")    # ВСТАВЬ ID канала-счётчика Trades (voice channel)
TICKETS_COUNTER_ID = env_id("TICKETS_COUNTER_ID")   # ВСТАВЬ ID канала-счётчика Tickets (voice channel)
tickets_solved = 0

# подсчёт перебирает весь архив тредов (сейчас 111 штук и растёт), поэтому
# держим результат в кэше, а на новый тред просто прибавляем единицу
_trades_cache = {"value": None, "at": None}
TRADES_CACHE_TTL = 600  # сек


async def count_trades(force=False):
    """count real threads (active + archived) in both trade forums"""
    now = datetime.now(timezone.utc)
    if (not force and _trades_cache["value"] is not None and _trades_cache["at"]
            and (now - _trades_cache["at"]).total_seconds() < TRADES_CACHE_TTL):
        return _trades_cache["value"]
    total = 0
    for guild in bot.guilds:
        for cid in (TEAM_TRADES_CHANNEL_ID, USER_TRADES_CHANNEL_ID):
            forum = guild.get_channel(cid)
            if forum is None:
                continue
            try:
                # active threads
                active = [t for t in forum.threads]
                total += len(active)
                # archived threads
                async for t in forum.archived_threads(limit=None):
                    total += 1
            except Exception as e:
                print(f"count_trades error: {e}")
                return _trades_cache["value"] or total  # не затираем кэш неполным числом
    _trades_cache["value"] = total
    _trades_cache["at"] = now
    return total

async def update_counter_channels(force=False):
    trades_now = await count_trades(force=force)
    for guild in bot.guilds:
        if MEMBERS_COUNTER_ID:
            ch = guild.get_channel(MEMBERS_COUNTER_ID)
            if ch:
                try:
                    cnt = len(guild.members) if guild.chunked else guild.member_count
                    new = f"👥 Members: {cnt}"
                    if ch.name != new:
                        await ch.edit(name=new)
                except Exception:
                    pass
        if TRADES_COUNTER_ID:
            ch = guild.get_channel(TRADES_COUNTER_ID)
            if ch:
                try:
                    new = f"📊 Trades: {trades_now}"
                    if ch.name != new:
                        await ch.edit(name=new)
                except Exception:
                    pass
        if TICKETS_COUNTER_ID:
            ch = guild.get_channel(TICKETS_COUNTER_ID)
            if ch:
                try:
                    new = f"🎫 Tickets: {tickets_solved}"
                    if ch.name != new:
                        await ch.edit(name=new)
                except Exception:
                    pass


# ==================================================================
#                    LEADERBOARD
# ==================================================================
lb_state = {"all_msg": 0, "week_msg": 0, "month_msg": 0, "week_start": "", "month": "",
            "week_final_msg": 0, "month_final_msg": 0, "league_msg": 0, "pnl_msg": 0}

def load_lb_state():
    global lb_state, trades_counter, tickets_solved
    if os.path.exists(LB_STATE_FILE):
        try:
            with open(LB_STATE_FILE, "r") as f:
                data = json.load(f)
                lb_state.update(data.get("lb", {}))
                trades_counter = data.get("trades_counter", TRADES_START_COUNT)
                tickets_solved = data.get("tickets_solved", 0)
        except Exception as e:
            print(f"lb state load error: {e}")

def save_lb_state():
    save_json_atomic(LB_STATE_FILE,
                     {"lb": lb_state, "trades_counter": trades_counter, "tickets_solved": tickets_solved},
                     "lb state")

def top_list(period, guild, limit=10):
    ranked = sorted(points.items(), key=lambda kv: kv[1].get(period, 0), reverse=True)
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    rank = 0
    for uid, pdata in ranked:
        val = pdata.get(period, 0)
        if val <= 0:
            continue
        member = guild.get_member(uid)
        if member is None or is_no_points(member):
            continue
        prefix = medals[rank] if rank < 3 else f"{E_PLUS}"
        name = member.display_name
        lines.append(f"{prefix} **{name}** - {val} {E_R}")
        rank += 1
        if rank >= limit:
            break
    return "\n".join(lines) if lines else "Пока пусто. Будь первым."

def lb_embed(title, emoji, period, guild):
    embed = discord.Embed(title=f"{emoji} {title}", description=top_list(period, guild), color=0xd7ecff)
    embed.set_footer(text=f"Updated • {datetime.now(PRAGUE).strftime('%d.%m %H:%M')}")
    return embed

async def purge_pin_notice(channel, tries=5):
    """Убрать системное "закрепил(а) сообщение".

    Discord присылает его отдельным сообщением с небольшой задержкой, поэтому
    одной проверки мало - ждём и пробуем несколько раз.
    """
    for _ in range(tries):
        await asyncio.sleep(1)
        try:
            async for m in channel.history(limit=10):
                if m.type == discord.MessageType.pins_add:
                    await m.delete()
                    return True
        except Exception as e:
            print(f"[leaderboard] не смог убрать уведомление о закрепе: {e}")
            return False
    return False


async def unpin_by_id(channel, msg_id):
    if not msg_id:
        return
    try:
        msg = await channel.fetch_message(msg_id)
        if msg.pinned:
            await msg.unpin()
    except Exception:
        pass  # сообщение могли удалить руками - это нормально


async def post_final_standings(channel, slot_key, embed):
    """Итоги недели/месяца: запостить, открепить прошлые, закрепить новые.

    Раньше итоги просто отправлялись. Закрепа не было, поэтому они тонули в
    истории, а у Discord ещё и лимит в 50 закрепов на канал - копить их нельзя,
    прошлые нужно откреплять.
    """
    msg = await channel.send(embed=embed)
    await unpin_by_id(channel, lb_state.get(slot_key))
    try:
        await msg.pin()
        lb_state[slot_key] = msg.id
        save_lb_state()
        await purge_pin_notice(channel)
    except Exception as e:
        print(f"[leaderboard] не удалось закрепить итоги ({slot_key}): {e}")
    return msg


async def get_or_create_lb_message(channel, slot_key, title, emoji, period, guild):
    """edit existing pinned msg or create new, store id in lb_state"""
    msg_id = lb_state.get(slot_key, 0)
    embed = lb_embed(title, emoji, period, guild)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except Exception:
            pass
    # create new
    msg = await channel.send(embed=embed)
    lb_state[slot_key] = msg.id
    save_lb_state()
    try:
        await msg.pin()
        await purge_pin_notice(channel)
    except Exception as e:
        print(f"[leaderboard] не удалось закрепить табло ({slot_key}): {e}")


def week_key_to_end(week_key):
    """'2026-W32' -> '16.08.2026' (воскресенье, которым неделя закончилась)."""
    try:
        return datetime.strptime(week_key + "-0", "%Y-W%W-%w").strftime("%d.%m.%Y")
    except Exception:
        return week_key


def month_key_to_label(month_key):
    """'2026-07' -> '07.2026'"""
    try:
        y, m = month_key.split("-")
        return f"{m}.{y}"
    except Exception:
        return month_key

async def get_or_create_league_message(channel, guild):
    """Живое табло лиги - четвёртое закреплённое сообщение рядом с тремя другими.

    Без него метка чемпиона на роли концепта была бы значком без объяснения:
    таблица выходит раз в месяц и тонет в истории.
    """
    rows = collect_league(guild, "month")
    embed = league_embed(rows, f"{E_EAGLE} CONCEPT LEAGUE",
                         f"Текущий сезон • {datetime.now(PRAGUE):%m.%Y}")
    if CHAMPION_MARK and rows:
        embed.add_field(
            name=f"Что значит {CHAMPION_MARK} у роли концепта",
            value=f"Знак чемпиона прошлого сезона. Его носят все участники "
                  f"победившего концепта, и в конце месяца он переходит новому лидеру.",
            inline=False)
    msg_id = lb_state.get("league_msg", 0)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except Exception:
            pass
    msg = await channel.send(embed=embed)
    lb_state["league_msg"] = msg.id
    save_lb_state()
    try:
        await msg.pin()
        await purge_pin_notice(channel)
    except Exception as e:
        print(f"[league] не удалось закрепить табло: {e}")


async def get_or_create_pnl_message(channel):
    """Живое табло общего счёта. Без него /pnl знали бы полтора человека:
    команду, о которой не написано, никто не наберёт."""
    recs = declared_records()
    embed = pnl_embed(recs, f"{E_LOGO} СЧЁТ СЕРВЕРА",
                      "Только заявленные сделки. Заявить свою: /trade")
    live, stale = open_declarations()
    if live or stale:
        val = []
        if live:
            val.append(f"{len(live)} {plural(len(live), 'заявка', 'заявки', 'заявок')} "
                       f"ещё не закрыта")
        if stale:
            val.append(f"брошено без закрытия: {len(stale)}")
        embed.add_field(name="Сейчас в рынке", value="\n".join(val), inline=False)
    msg_id = lb_state.get("pnl_msg", 0)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except Exception:
            pass
    msg = await channel.send(embed=embed)
    lb_state["pnl_msg"] = msg.id
    save_lb_state()
    try:
        await msg.pin()
        await purge_pin_notice(channel)
    except Exception as e:
        print(f"[pnl] не удалось закрепить табло: {e}")


@tasks.loop(minutes=60)
@loop_guard("leaderboard")
async def leaderboard_loop():
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return
    guild = channel.guild
    await get_or_create_lb_message(channel, "all_msg", "ALL-TIME LEADERBOARD", E_LOGO, "all", guild)
    await get_or_create_lb_message(channel, "month_msg", "MONTHLY LEADERBOARD", E_TIGER, "month", guild)
    await get_or_create_lb_message(channel, "week_msg", "WEEKLY LEADERBOARD", E_EAGLE, "week", guild)
    await get_or_create_league_message(channel, guild)
    await get_or_create_pnl_message(channel)
    await get_or_create_exam_message(channel)

@tasks.loop(minutes=1)
@loop_guard("period-reset")
async def period_reset_loop():
    """check for weekly (Mon 00:00) and monthly (1st 00:00) resets"""
    now = datetime.now(PRAGUE)
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return
    guild = channel.guild

    # weekly reset: как только сменилась календарная неделя.
    # Раньше требовалось попасть ровно в понедельник 00:00 - любой даунтайм в эту
    # минуту отменял сброс на всю неделю. Теперь сверяем ключ недели.
    iso_week = now.strftime("%Y-W%W")
    if not lb_state.get("week_start"):
        lb_state["week_start"] = iso_week   # первый запуск: запомнить, не сбрасывая
        save_lb_state()
    elif lb_state["week_start"] != iso_week:
        # подпись по ключу ЗАВЕРШИВШЕЙСЯ недели: публикация идёт уже в новой,
        # и дата публикации назвала бы не тот период
        ended = week_key_to_end(lb_state["week_start"])
        final = discord.Embed(title=f"{E_EAGLE} WEEKLY RESULTS", description=top_list("week", guild), color=0xd7ecff)
        final.set_footer(text=f"Week ended • {ended}")
        await post_final_standings(channel, "week_final_msg", final)
        # Сводка ОБЯЗАТЕЛЬНО до обнуления: она читает недельные корзины, и после
        # сброса заработок и лига недели вышли бы нулями.
        await post_weekly_digest(guild, ended)
        for uid in points:
            points[uid]["week"] = 0
        save_points()
        lb_state["week_start"] = iso_week
        save_lb_state()
        # сделка недели: лучшая закрытая заявка, публичное признание + бонус
        best = best_trade_of_week(datetime.now(timezone.utc))
        if best and best[1]["result_r"] > 0:
            tid, brec = best
            member = guild.get_member(brec["uid"])
            if member:
                add_points(member, R_TRADE_OF_WEEK)
            url = f"https://discord.com/channels/{guild.id}/{tid}"
            tow = discord.Embed(
                title="🏆 Сделка недели",
                description=(f"{brec['instrument']} **{brec['result_r']:+.2f}R** - "
                             f"<@{brec['uid']}>\n"
                             f"Заявлена до исхода, закрыта по правилам. "
                             f"[Тред сделки]({url})\n"
                             f"+{R_TRADE_OF_WEEK} {E_R} автору."),
                color=0xd7ecff)
            try:
                await channel.send(embed=tow,
                                   allowed_mentions=discord.AllowedMentions(users=False))
            except Exception as e:
                print(f"[trade-of-week] не ушла: {e}")

    # monthly reset: как только сменился календарный месяц (та же логика, что и с неделей)
    month_key = now.strftime("%Y-%m")
    if not lb_state.get("month"):
        lb_state["month"] = month_key
        save_lb_state()
    elif lb_state["month"] != month_key:
        # то же самое: итоги июля публикуются 1 августа, поэтому месяц берём из
        # сохранённого ключа, иначе июльский рекап подписывался как 08.2026
        ended_key = lb_state["month"]
        ended = month_key_to_label(ended_key)
        final = discord.Embed(title=f"{E_TIGER} MONTHLY RESULTS", description=top_list("month", guild), color=0xd7ecff)
        final.set_footer(text=f"Month ended • {ended}")
        await post_final_standings(channel, "month_final_msg", final)
        # следом - разрез по концептам за тот же месяц
        try:
            since = datetime.strptime(ended_key, "%Y-%m").replace(tzinfo=PRAGUE).astimezone(timezone.utc)
            stats, skipped, totals = await collect_concept_stats(guild, since)
            await channel.send(embed=concept_stats_embed(
                stats, skipped, totals, f"{E_LOGO} Концепты - итоги месяца", f"За {ended}.",
                CONCEPT_MIN_SAMPLE_MONTH))
        except Exception as e:
            print(f"[concept-stats] месячный пост не вышел: {e}")
        try:
            rows = collect_league(guild, "month")
            await channel.send(embed=league_embed(
                rows, f"{E_EAGLE} Лига концептов - итоги сезона", f"Сезон {ended}."))
            if rows:
                await move_champion_mark(guild, rows[0][0])
        except Exception as e:
            print(f"[league] итог сезона не вышел: {e}")
        for uid in points:
            points[uid]["month"] = 0
        save_points()
        lb_state["month"] = month_key
        save_lb_state()


@tasks.loop(minutes=10)
@loop_guard("counters")
async def counters_loop():
    try:
        await update_counter_channels(force=True)  # раз в 10 минут сверяемся с Discord
    except Exception as e:
        print(f"counters loop error: {e}")



# ==================================================================
#              GATE REMINDER (DM тем, кто не выбрал концепт)
# ==================================================================
GATE_REMINDER_TEXTS = [
    "Привет! 👋\n\n"
    "Ты зашёл на сервер, но пока не выбрал концепт - поэтому всё, кроме канала "
    "выбора, для тебя закрыто.\n\n"
    "Чтобы открыть доступ, зайди в <#{ch}> и нажми концепт, который торгуешь: "
    "MLTF, Market Profile, 0DTE, Order Flow, Price Action или Swing. Это займёт пять секунд.",

    "Напоминаю: доступ к серверу всё ещё закрыт, потому что не выбран концепт.\n\n"
    "Открыть: <#{ch}> - нажми свой концепт. Если не знаешь, что выбрать, рядом есть "
    "панель с коротким описанием каждого.\n\n"
    "Больше напоминаний не будет.",
]


def seed_gate_reminders(guild):
    """Первый запуск: считаем всех, кто уже сидит в гейте, отработанными.

    Иначе при включении фичи сразу прилетит рассылка всем 45 застрявшим, причём
    большинству из них - повторно.
    """
    global gate_reminders_seeded
    if gate_reminders_seeded:
        return
    gate = guild.get_role(GATE_ROLE_ID)
    if gate is None:
        return
    done = len(GATE_REMINDER_STAGES)
    for member in gate.members:
        gate_reminders.setdefault(str(member.id), done)
    gate_reminders_seeded = True
    save_runtime_state()
    print(f"[gate-reminder] помечено как отработанные: {len(gate_reminders)} участников")


@tasks.loop(minutes=10)
@loop_guard("gate-reminder")
async def gate_reminder_loop():
    now = datetime.now(timezone.utc)
    stages = len(GATE_REMINDER_STAGES)
    changed = False
    for guild in bot.guilds:
        gate = guild.get_role(GATE_ROLE_ID)
        if gate is None:
            continue
        seed_gate_reminders(guild)
        for member in list(gate.members):
            if member.bot or is_service(member) or is_gate_exempt(member) or has_concept(member):
                continue
            key = str(member.id)
            sent = gate_reminders.get(key, 0)
            if sent >= stages or member.joined_at is None:
                continue
            if (now - member.joined_at).total_seconds() < GATE_REMINDER_STAGES[sent]:
                continue
            try:
                await member.send(GATE_REMINDER_TEXTS[sent].format(ch=GATE_PANEL_CHANNEL_ID))
                print(f"[gate-reminder] напоминание {sent + 1} -> {member.name}")
            except Exception as e:
                # чаще всего закрытые ЛС - повторять бессмысленно, помечаем отправленным
                print(f"[gate-reminder] не доставлено {member.name}: {type(e).__name__}")
            gate_reminders[key] = sent + 1
            changed = True
            await asyncio.sleep(1.2)   # не долбим Discord пачкой DM

    # подчистить тех, кто уже вышел из гейта, чтобы словарь не рос
    live = {str(m.id) for g in bot.guilds
            for m in (g.get_role(GATE_ROLE_ID).members if g.get_role(GATE_ROLE_ID) else [])}
    for key in [k for k in gate_reminders if k not in live]:
        del gate_reminders[key]
        changed = True
    if changed:
        save_runtime_state()

# ==================================================================
#                    VOICE AUTOSAVE
# ==================================================================
@tasks.loop(minutes=5)
@loop_guard("voice-autosave")
async def voice_autosave():
    now = datetime.now(timezone.utc)
    changed = False
    for uid in list(voice_join_times.keys()):
        joined = voice_join_times[uid]
        secs = (now - joined).total_seconds()
        if secs > 0:
            voice_totals[uid] = voice_totals.get(uid, 0) + secs
            voice_join_times[uid] = now
            changed = True
    if changed:
        save_stats()
        save_sessions()
    settle_voice_r()


# ==================================================================
#                    ON READY
# ==================================================================
@bot.event
async def on_ready():
    load_stats()
    load_sessions()
    load_points()
    load_rcredit()
    load_lb_state()
    load_role_memory()
    load_runtime_state()
    load_shop_state()
    load_bets()
    load_session_state()
    load_blind_state()
    load_declared()
    load_auction()
    load_exam()
    load_arena()
    load_fantasy()
    repair_balances()
    await reconcile_voice_on_start()
    await cache_invites()
    bot.add_view(ConceptView())
    bot.add_view(ConceptDescView())
    bot.add_view(NewsView())
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    bot.add_view(StatsView())
    bot.add_view(ShopView())
    bot.add_view(BetView())
    bot.add_view(BlindView())
    bot.add_view(DeclaredView())
    bot.add_view(AuctionView())
    bot.add_view(ArenaView())
    bot.add_view(FantasyView(fantasy.get('pool') or None))
    if not news_loop.is_running():
        news_loop.start()
    if not event_loop.is_running():
        event_loop.start()
    if not voice_autosave.is_running():
        voice_autosave.start()
    if not leaderboard_loop.is_running():
        leaderboard_loop.start()
    if not period_reset_loop.is_running():
        period_reset_loop.start()
    if not counters_loop.is_running():
        counters_loop.start()
    if not gate_reminder_loop.is_running():
        gate_reminder_loop.start()
    if not shop_loop.is_running():
        shop_loop.start()
    ECHO_FORUMS.update({
        TEAM_TRADES_CHANNEL_ID: "trade",
        USER_TRADES_CHANNEL_ID: "trade",
        PREMARKETS_CHANNEL_ID: "premarket",
        BACKTESTS_CHANNEL_ID: "backtest",
    })
    if not session_loop.is_running():
        session_loop.start()
    if not echo_loop.is_running():
        echo_loop.start()
    if not blind_loop.is_running():
        blind_loop.start()
    if not bet_settle_loop.is_running():
        bet_settle_loop.start()
    if not premarket_loop.is_running():
        premarket_loop.start()
    if not declare_nag_loop.is_running():
        declare_nag_loop.start()
    if not auction_loop.is_running():
        auction_loop.start()
    if not arena_loop.is_running():
        arena_loop.start()
    if not fundcard_loop.is_running():
        fundcard_loop.start()
    if not fantasy_loop.is_running():
        fantasy_loop.start()
    await update_counter_channels(force=True)
    print(f"Живой: {bot.user}")


# ==================================================================
#                    SLASH COMMANDS
# ==================================================================
@bot.slash_command(name="panel", description="Панель выбора концептов")
@discord.default_permissions(administrator=True)
async def panel(ctx):
    embed = discord.Embed(
        title="Выбери концепции, которые торгуешь, что бы получить доступ к серверу",
        description="Клик по кнопке - взял/снял роль. Можно сколько угодно.\nПервый выбор открывает весь сервер.",
        color=0xd7ecff)
    embed.set_author(name="where fear ends, freedom begins", icon_url=BRAND_ICON_URL)
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=ConceptView())

@bot.slash_command(name="conceptinfo", description="Панель описания концептов")
@discord.default_permissions(administrator=True)
async def conceptinfo(ctx):
    embed = discord.Embed(
        title="Не знаешь, что это за концепт?",
        description="Нажми на кнопку - появится краткое описание концепции (видно только тебе).",
        color=0xd7ecff)
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=ConceptDescView())

@bot.slash_command(name="newspanel", description="Панель подписки на новости")
@discord.default_permissions(administrator=True)
async def newspanel(ctx):
    embed = discord.Embed(
        title="Подписка на новости",
        description="🔴 News Red - пинг перед новостями высокой важности (High)\n🟠 News Orange - пинг перед новостями средней важности (Medium)\n🌍 NewsGeo - геополитические новости (Иран, Израиль, Трамп, нефть и т.д.)\n\nКлик по кнопке - включил/выключил пинги.",
        color=0xd7ecff)
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=NewsView())

@bot.slash_command(name="ticketpanel", description="Панель тикетов поддержки")
@discord.default_permissions(administrator=True)
async def ticketpanel(ctx):
    embed = discord.Embed(
        title="SUPPORT TICKET PANEL",
        description=(
            "**How It Works?**\n\n"
            "**Open a Ticket** - Click the button below to request assistance.\n"
            "*Открыть тикет - Нажми кнопку ниже, чтобы запросить помощь.*\n\n"
            "**Describe Your Issue** - Tell us what you need help with: trading question, account access, or technical issue.\n"
            "*Опиши свою проблему - Расскажи, с чем нужна помощь: вопрос по трейдингу, доступ к аккаунту или техническая проблема.*\n\n"
            "**Get Support** - A team member will review your ticket and respond as soon as possible.\n"
            "*Получи поддержку - Участник команды рассмотрит твой тикет и ответит как можно скорее.*\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "**Why Use This System?**\n\n"
            "**Simple & Fast** - Opening a ticket takes just a few clicks.\n"
            "*Просто и быстро - Открыть тикет пара кликов.*\n\n"
            "**Direct Routing** - Your request goes straight to the right person.\n"
            "*Прямая маршрутизация - Запрос сразу идёт нужному человеку.*\n\n"
            "**Tracked & Organized** - Every ticket is handled properly, nothing gets lost.\n"
            "*Отслеживается и организовано - Каждый тикет обрабатывается как надо, ничего не теряется.*"
        ),
        color=0xd7ecff)
    embed.set_footer(text="inter hominem esse", icon_url=BRAND_ICON_URL)
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=TicketOpenView())

@bot.slash_command(name="statspanel", description="Панель статистики")
@discord.default_permissions(administrator=True)
async def statspanel(ctx):
    embed = discord.Embed(
        title="Твоя статистика",
        description="Нажми кнопку, чтобы увидеть свою статистику: дни, войс, очки R, концепты, подписки.",
        color=0xd7ecff)
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=StatsView())

@bot.slash_command(name="givepoints", description="Выдать/снять R вручную (админ)")
@discord.default_permissions(administrator=True)
async def givepoints(ctx, member: discord.Member, amount: int):
    rec = points.setdefault(member.id, {"all": 0, "week": 0, "month": 0})
    if amount < 0 and rec.get("all", 0) + amount < rec.get("spent", 0):
        # иначе человек остался бы должен: потрачено больше, чем заработано
        await ctx.respond(
            f"Нельзя: у {member.display_name} потрачено {rec.get('spent', 0)} R, "
            f"после снятия заработано стало бы меньше. Максимум к снятию: "
            f"{rec.get('all', 0) - rec.get('spent', 0)} R.", ephemeral=True)
        return
    rec["all"] += amount
    rec["week"] += amount
    rec["month"] += amount
    save_points()
    await ctx.respond(
        f"{member.display_name}: {'+' if amount >= 0 else ''}{amount} R · "
        f"заработано {rec['all']}, баланс {balance(member.id)}", ephemeral=True)

@bot.slash_command(name="checkpoints", description="Узнать сколько R у участника (админ)")
@discord.default_permissions(administrator=True)
async def checkpoints(ctx, member: discord.Member):
    p = points.get(member.id, {"all": 0, "week": 0, "month": 0})
    await ctx.respond(f"{member.display_name}: всего {p['all']} R | неделя {p['week']} | месяц {p['month']}", ephemeral=True)

@bot.slash_command(name="ticketsolved", description="+1 к счётчику решённых тикетов (админ)")
@discord.default_permissions(administrator=True)
async def ticketsolved(ctx):
    global tickets_solved
    tickets_solved += 1
    save_lb_state()
    await update_counter_channels()
    await ctx.respond(f"Tickets solved: {tickets_solved}", ephemeral=True)


# ==================================================================
#                          SHOP (трата R)
# ==================================================================
# Баланс = заработано минус потрачено. Лидерборд продолжает показывать
# ЗАРАБОТАННОЕ, иначе покупка роняла бы человека в рейтинге - за трату очков
# наказывать нельзя, иначе магазином никто не пользуется.
SHOP_CHANNEL_ID = env_id("SHOP_CHANNEL_ID")   # │shop
SHOP_STATE_FILE = "shop_state.json"

SHOP_ITEMS = {
    # Закреп трейда сюда не попал намеренно: Discord держит максимум ОДИН
    # закреплённый тред на форум (код ошибки 30047), а в user-trades слот занят
    # правилами. Дефицитный слот приберегли под еженедельный аукцион.
    "ticket_priority": {
        "label": "Приоритет в тикетах",
        "desc": "Твои тикеты команда видит первыми, 30 дней",
        "price": 15, "emoji": "🎫", "kind": "role_temp", "role_key": "priority", "days": 30,
    },
    "color_ice": {
        "label": "Цвет ника - Ice",
        "desc": "Подсветка ника на 14 дней",
        "price": 30, "emoji": "🧊", "kind": "role_temp", "role_key": "color_ice", "days": 14,
    },
    "color_amber": {
        "label": "Цвет ника - Amber",
        "desc": "Подсветка ника на 14 дней",
        "price": 30, "emoji": "🟠", "kind": "role_temp", "role_key": "color_amber", "days": 14,
    },
    "color_mint": {
        "label": "Цвет ника - Mint",
        "desc": "Подсветка ника на 14 дней",
        "price": 30, "emoji": "🌿", "kind": "role_temp", "role_key": "color_mint", "days": 14,
    },
    "color_rose": {
        "label": "Цвет ника - Rose",
        "desc": "Подсветка ника на 14 дней",
        "price": 30, "emoji": "🌹", "kind": "role_temp", "role_key": "color_rose", "days": 14,
    },
    "stream_topic": {
        "label": "Тема эфира",
        "desc": "Выбираешь тему следующего разбора",
        "price": 75, "emoji": "🎬", "kind": "manual",
    },
    "trade_review": {
        "label": "Разбор твоей сделки",
        "desc": "Команда разбирает твою сделку лично",
        "price": 120, "emoji": "🔍", "kind": "manual",
    },
}

# id ролей магазина: заполняются после создания (см. SHOP_ROLE_IDS ниже)
SHOP_ROLE_IDS = {
    "priority": env_id("SHOP_ROLE_PRIORITY"),
    "color_ice": env_id("SHOP_ROLE_COLOR_ICE"),
    "color_amber": env_id("SHOP_ROLE_COLOR_AMBER"),
    "color_mint": env_id("SHOP_ROLE_COLOR_MINT"),
    "color_rose": env_id("SHOP_ROLE_COLOR_ROSE"),
}

# активные покупки со сроком: [{uid, kind, role_id/thread_id, until}]
shop_grants = []


def load_shop_state():
    global shop_grants
    if os.path.exists(SHOP_STATE_FILE):
        try:
            with open(SHOP_STATE_FILE, "r") as f:
                shop_grants = json.load(f).get("grants", [])
        except Exception as e:
            print(f"shop state load error: {e}")
            shop_grants = []


def save_shop_state():
    save_json_atomic(SHOP_STATE_FILE, {"grants": shop_grants}, "shop state")


def balance(uid):
    rec = points.get(uid)
    if not rec:
        return 0
    return rec.get("all", 0) - rec.get("spent", 0)


def spend(uid, amount):
    """Списать R. Возвращает False, если не хватает."""
    if balance(uid) < amount:
        return False
    rec = points.setdefault(uid, {"all": 0, "week": 0, "month": 0})
    rec["spent"] = rec.get("spent", 0) + amount
    save_points()
    return True


def repair_balances():
    """Починить отрицательные балансы при старте.

    Баланс = заработано минус потрачено, и уйти ниже нуля он не должен: spend()
    это проверяет. Но правки через /givepoints, ручные вмешательства в файл или
    сбой на полпути могут оставить запись, где потрачено больше заработанного -
    такую находку нужно не прятать, а чинить и показывать.
    """
    fixed = []
    for uid, rec in points.items():
        bal = rec.get("all", 0) - rec.get("spent", 0)
        if bal < 0:
            rec["spent"] = rec.get("all", 0)      # обнуляем баланс, не уходя в минус
            fixed.append((uid, bal))
    if fixed:
        save_points()
        for uid, bal in fixed:
            print(f"[integrity] отрицательный баланс у {uid}: {bal} -> 0")
    return fixed


def refund(uid, amount):
    rec = points.get(uid)
    if rec:
        rec["spent"] = max(0, rec.get("spent", 0) - amount)
        save_points()


async def shop_log(guild, member, item, extra=""):
    ch = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if ch is None:
        return
    embed = discord.Embed(
        description=f"🛒 {member.mention} купил **{item['label']}** за {item['price']} {E_R}\n"
                    f"Остаток: {balance(member.id)} R{extra}",
        color=0xd7ecff)
    try:
        await ch.send(embed=embed)
    except Exception:
        pass


async def deliver_item(interaction, key, item):
    """Выдать товар. Возвращает (успех, текст ответа)."""
    member = interaction.user
    guild = interaction.guild
    kind = item["kind"]

    if kind == "role_temp":
        role_id = SHOP_ROLE_IDS.get(item["role_key"], 0)
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            return False, "Роль для этого товара не настроена, скажи админу."
        if role in member.roles:
            return False, f"У тебя уже есть «{item['label']}». Дождись окончания."
        mark_bot_edit(member.id)
        await member.add_roles(role, reason=f"покупка: {item['label']}")
        until = datetime.now(timezone.utc) + timedelta(days=item["days"])
        shop_grants.append({"uid": member.id, "kind": "role_temp", "role_id": role.id,
                            "label": item["label"], "until": until.isoformat()})
        save_shop_state()
        return True, f"Готово. «{item['label']}» с тобой до {until.astimezone(PRAGUE):%d.%m %H:%M}."

    # manual: заявка уходит команде
    ch = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if ch:
        embed = discord.Embed(
            title="🧾 Заявка из магазина",
            description=f"{member.mention} купил **{item['label']}** за {item['price']} R.\n"
                        f"Требуется ручная выдача.",
            color=0xffaa33)
        try:
            await ch.send(embed=embed)
        except Exception:
            pass
    return True, f"Заявка принята. Команда свяжется с тобой по «{item['label']}»."


class ShopSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{it['label']} - {it['price']} R",
                description=it["desc"][:100], value=key, emoji=it.get("emoji"))
            for key, it in SHOP_ITEMS.items()
        ]
        super().__init__(placeholder="Выбери товар", options=options,
                         custom_id="shop_select", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        item = SHOP_ITEMS.get(key)
        member = interaction.user
        if item is None:
            await interaction.response.send_message("Товар не найден.", ephemeral=True)
            return
        if balance(member.id) < item["price"]:
            await interaction.response.send_message(
                f"Не хватает R. Нужно {item['price']}, у тебя {balance(member.id)}.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        if not spend(member.id, item["price"]):
            await interaction.followup.send("Не хватает R.", ephemeral=True)
            return
        try:
            ok, text = await deliver_item(interaction, key, item)
        except Exception as e:
            ok, text = False, f"Не удалось выдать товар: {type(e).__name__}"
            print(f"[shop] ошибка выдачи {key} для {member.id}: {e}")
        if not ok:
            refund(member.id, item["price"])   # не смогли выдать - деньги назад
            await interaction.followup.send(f"{text}\nR не списаны.", ephemeral=True)
            return
        bump_week("spent", item["price"])
        bump_week("purchases")
        await shop_log(interaction.guild, member, item)
        await interaction.followup.send(f"{text}\nСписано {item['price']} R, остаток {balance(member.id)}.",
                                        ephemeral=True)


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShopSelect())

    @discord.ui.button(label="Мой баланс", style=discord.ButtonStyle.secondary,
                       custom_id="shop_balance", emoji="💰", row=1)
    async def show_balance(self, button, interaction):
        uid = interaction.user.id
        rec = points.get(uid, {})
        mine = [g for g in shop_grants if g["uid"] == uid]
        lines = [f"Баланс: **{balance(uid)}** {E_R}",
                 f"Заработано всего: {rec.get('all', 0)} · потрачено: {rec.get('spent', 0)}"]
        if mine:
            lines.append("\n**Активные покупки:**")
            for g in mine:
                until = datetime.fromisoformat(g["until"]).astimezone(PRAGUE)
                lines.append(f"· {g.get('label', 'покупка')} - до {until:%d.%m %H:%M}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tasks.loop(minutes=5)
@loop_guard("shop")
async def shop_loop():
    """Снять то, чему вышел срок."""
    now = datetime.now(timezone.utc)
    expired = [g for g in shop_grants if datetime.fromisoformat(g["until"]) <= now]
    if not expired:
        return
    for g in expired:
        try:
            if g["kind"] == "pin_thread":
                for guild in bot.guilds:
                    thread = guild.get_channel_or_thread(g["thread_id"])
                    if thread is None:
                        try:
                            thread = await bot.fetch_channel(g["thread_id"])
                        except Exception:
                            thread = None
                    if thread is not None:
                        await thread.edit(pinned=False, reason="срок закрепа истёк")
                        break
            elif g["kind"] == "role_temp":
                for guild in bot.guilds:
                    member = guild.get_member(g["uid"])
                    role = guild.get_role(g["role_id"])
                    if member and role and role in member.roles:
                        mark_bot_edit(member.id)
                        await member.remove_roles(role, reason="срок покупки истёк")
        except Exception as e:
            print(f"[shop] не смог снять покупку {g}: {e}")
        shop_grants.remove(g)
    save_shop_state()


@bot.slash_command(name="shoppanel", description="Опубликовать панель магазина (админ)")
@discord.default_permissions(administrator=True)
async def shoppanel(ctx):
    lines = [f"{it.get('emoji','')} **{it['label']}** - {it['price']} {E_R}\n{it['desc']}"
             for it in SHOP_ITEMS.values()]
    embed = discord.Embed(
        title="Магазин",
        description="R зарабатываются за трейды, разборы, время в войсе и респект.\n"
                    "Здесь их можно потратить.\n\n" + "\n\n".join(lines),
        color=0xd7ecff)
    embed.set_footer(text="Покупка списывает R, но не влияет на твоё место в лидерборде")
    await ctx.respond("Панель опубликована", ephemeral=True)
    await ctx.send(embed=embed, view=ShopView())


@bot.slash_command(name="balance", description="Показать баланс R")
async def balance_cmd(ctx, member: discord.Member = None):
    target = member or ctx.author
    rec = points.get(target.id, {})
    await ctx.respond(
        f"{target.display_name}: **{balance(target.id)}** R "
        f"(заработано {rec.get('all', 0)}, потрачено {rec.get('spent', 0)})",
        ephemeral=True)


# ==================================================================
#                     СТАВКИ НА МАКРОДАННЫЕ
# ==================================================================
# Ставка живёт прямо на алерте в новостном канале - там, где человек и так
# видит новость. Тотализатор: весь банк делится между угадавшими пропорционально
# ставкам. Выигрыш меняет БАЛАНС, но не лидерборд: рейтинг у нас за вклад в
# сообщество, а не за удачу.
BETS_FILE = "bets_state.json"
BET_STAKES = [5, 10, 25]        # фиксированные номиналы, свободного ввода нет
BET_CLOSE_BEFORE = 60           # за сколько секунд до выхода закрываем приём
# Ставим на РЕАКЦИЮ РЫНКА, а не на само число в отчёте. Причина простая:
# фид ForexFactory не отдаёт фактические значения вообще (проверено на 17
# прошедших событиях - поле пустое у всех), поэтому расчёт «выше/ниже прогноза»
# был невозможен в принципе. Реакцию же мы измеряем точно, по тем же котировкам,
# что и слепой график. Для трейдера предсказать движение и полезнее, чем цифру.
BET_INSTRUMENT = "NQ=F"
BET_INSTRUMENT_NAME = "Nasdaq"
BET_REACTION_MIN = 30           # на каком горизонте меряем реакцию
BET_SETTLE_DELAY_MIN = 5        # ждём ещё столько, чтобы свечи успели появиться

open_bets = {}   # msg_id (str) -> {key, title, forecast, dt, bets:{uid:{side,amount}}, settled}


def load_bets():
    global open_bets
    if os.path.exists(BETS_FILE):
        try:
            with open(BETS_FILE, "r") as f:
                open_bets = json.load(f)
        except Exception as e:
            print(f"bets load error: {e}")
            open_bets = {}


BETS_KEEP_DAYS = 3       # рассчитанные ставки держим недолго - только на разбор


def prune_bets():
    """Выкинуть рассчитанные ставки: без этого файл и линейный поиск в
    settle_bets растут без предела - примерно 500 записей в год."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=BETS_KEEP_DAYS)
    for mid in [m for m, b in list(open_bets.items()) if b.get("settled")]:
        try:
            if datetime.fromisoformat(open_bets[mid]["dt"]) < cutoff:
                del open_bets[mid]
        except Exception:
            del open_bets[mid]      # мусорная запись - тоже под нож


def save_bets():
    prune_bets()
    save_json_atomic(BETS_FILE, open_bets, "bets")


def credit(uid, amount):
    """Начислить R на баланс, не трогая заработанное (лидерборд не двигается)."""
    rec = points.setdefault(uid, {"all": 0, "week": 0, "month": 0})
    rec["spent"] = rec.get("spent", 0) - amount
    save_points()


def parimutuel_payout(players, win_side):
    """Разделить весь банк между угадавшими пропорционально ставкам.

    Вынесено отдельно, потому что этой же математикой считается и слепой график.
    Возвращает [(uid, ставка, выплата)]; пусто, если не угадал никто.
    """
    pool = sum(b["amount"] for b in players.values())
    winners = {u: b for u, b in players.items() if b["side"] == win_side}
    win_total = sum(b["amount"] for b in winners.values())
    if not winners:
        return []
    return [(int(uid), b["amount"], int(round(pool * b["amount"] / win_total)))
            for uid, b in winners.items()]


def parse_num(raw):
    """'225K' -> 225000, '3.2%' -> 3.2, '-1.5' -> -1.5. None, если не число."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".").replace("%", "").replace("$", "")
    if not s:
        return None
    mult = 1
    if s and s[-1] in "KkMmBb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


async def market_reaction(event_dt):
    """Куда ушёл рынок за BET_REACTION_MIN после выхода.

    -> ("up"/"down", изменение в %, цена до, цена после) либо None, если данных нет.
    """
    ev = int(event_dt.timestamp())
    candles = await fetch_candles(BET_INSTRUMENT, rng="5d", interval="5m")
    before = [c for c in candles if c[0] <= ev]
    after = [c for c in candles if ev < c[0] <= ev + BET_REACTION_MIN * 60]
    if not before or not after:
        return None
    ref, end = before[-1][4], after[-1][4]
    if not ref:
        return None
    return ("up" if end > ref else "down"), (end - ref) / ref * 100, ref, end


class BetButton(discord.ui.Button):
    def __init__(self, side, amount):
        arrow = "▲" if side == "up" else "▼"
        super().__init__(label=f"{arrow} {amount} R",
                         style=discord.ButtonStyle.secondary,
                         custom_id=f"bet_{side}_{amount}",
                         row=0 if side == "up" else 1)
        self.side = side
        self.amount = amount

    async def callback(self, interaction: discord.Interaction):
        mid = str(interaction.message.id)
        bet = open_bets.get(mid)
        if bet is None or bet.get("settled"):
            await interaction.response.send_message("Приём ставок по этой новости закрыт.", ephemeral=True)
            return
        try:
            release = datetime.fromisoformat(bet["dt"])
        except Exception:
            release = None
        if release and (release - datetime.now(timezone.utc)).total_seconds() < BET_CLOSE_BEFORE:
            await interaction.response.send_message("Поздно - новость вот-вот выйдет.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid in bet["bets"]:
            old = bet["bets"][uid]
            arrow = "вверх" if old["side"] == "up" else "вниз"
            await interaction.response.send_message(
                f"Ты уже поставил {old['amount']} R на «{arrow}». Одна ставка на новость.", ephemeral=True)
            return
        if balance(interaction.user.id) < self.amount:
            await interaction.response.send_message(
                f"Не хватает R: нужно {self.amount}, у тебя {balance(interaction.user.id)}.", ephemeral=True)
            return

        if not spend(interaction.user.id, self.amount):
            await interaction.response.send_message("Не хватает R.", ephemeral=True)
            return
        bet["bets"][uid] = {"side": self.side, "amount": self.amount}
        save_bets()
        arrow = f"{BET_INSTRUMENT_NAME} вверх" if self.side == "up" else f"{BET_INSTRUMENT_NAME} вниз"
        pool = sum(b["amount"] for b in bet["bets"].values())
        await interaction.response.send_message(
            f"Принято: {self.amount} R на «{arrow}».\nВ банке {pool} R, "
            f"ставок {len(bet['bets'])}. Остаток: {balance(interaction.user.id)} R.", ephemeral=True)


class BetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for side in ("up", "down"):
            for amount in BET_STAKES:
                self.add_item(BetButton(side, amount))


async def settle_one_bet(mid, bet):
    """Рассчитать ставку по реакции рынка. Возвращает текст итога или None."""
    try:
        event_dt = datetime.fromisoformat(bet["dt"])
    except Exception:
        bet["settled"] = True
        save_bets()
        return None

    reaction = await market_reaction(event_dt)
    players = bet["bets"]

    if reaction is None:
        # котировок вокруг события нет - возвращаем ставки, а не гадаем
        for uid, b in players.items():
            credit(int(uid), b["amount"])
        bet["settled"] = True
        save_bets()
        if not players:
            return None
        return (f"Котировок вокруг выхода не нашлось, ставки возвращены "
                f"({len(players)} шт).")

    side, change, ref, end = reaction
    bet["settled"] = True
    bet["reaction"] = {"side": side, "change": change}
    where = "вверх" if side == "up" else "вниз"
    head = (f"{BET_INSTRUMENT_NAME} после выхода ушёл **{where}** на {abs(change):.2f}% "
            f"за {BET_REACTION_MIN} минут.")

    if not players:
        save_bets()
        return head + "\n\nСтавок не было."

    pool = sum(b["amount"] for b in players.values())
    payouts = parimutuel_payout(players, side)
    for uid, _stake, share in payouts:
        credit(uid, share)
    save_bets()

    if not payouts:
        return head + (f"\n\nНикто не угадал. Банк {pool} {E_R} сгорел "
                       f"({len(players)} ставок на одну сторону).")
    lines = [f"<@{u}> - ставил {st}, забрал {sh}"
             for u, st, sh in sorted(payouts, key=lambda x: -x[2])[:10]]
    return head + (f"\n\nБанк {pool} {E_R} на {len(payouts)} угадавших "
                   f"из {len(players)}.\n\n" + "\n".join(lines))


@tasks.loop(minutes=5)
@loop_guard("bet-settle")
async def bet_settle_loop():
    """Считает всё, чему пришёл срок.

    Раньше расчёт жил внутри поста с итогом новости и срабатывал только в окне
    9-12 минут после выхода. Окно легко пропускалось - и ставка зависала
    навсегда вместе с деньгами. Теперь это отдельный проход: если срок вышел,
    ставка будет посчитана, сколько бы времени ни прошло.
    """
    now = datetime.now(timezone.utc)
    for mid, bet in list(open_bets.items()):
        if bet.get("settled"):
            continue
        try:
            ev = datetime.fromisoformat(bet["dt"])
        except Exception:
            bet["settled"] = True
            save_bets()
            continue
        if now < ev + timedelta(minutes=BET_REACTION_MIN + BET_SETTLE_DELAY_MIN):
            continue
        text = await settle_one_bet(mid, bet)
        if not text:
            continue
        channel = bot.get_channel(bet.get("channel_id") or NEWS_CHANNEL_ID)
        if channel is None:
            continue
        embed = discord.Embed(title=f"🎲 Итог ставок: {bet['title']}",
                              description=text, color=0xd7ecff)
        try:
            await channel.send(embed=embed,
                               allowed_mentions=discord.AllowedMentions(users=False))
        except Exception as e:
            print(f"[bets] итог не ушёл: {e}")


# ==================================================================
#                  СТАТИСТИКА ПО КОНЦЕПТАМ
# ==================================================================
# Исход сделки берём из ЗАГОЛОВКА треда - именно там участники его и пишут
# (TP/SL/BE и величина в RR). Реакции для этого не годятся: бот сам ставит плюс
# и минус каждому треду, так что они ничего не различают.
#
# Важная оговорка в формулировках: роль концепта значит «трейдер этого концепта»,
# а не «сделка сделана этим методом». Поэтому в постах пишем «трейдеры MLTF»,
# а не «метод MLTF даёт столько-то».
# Порог зависит от периода: за всё время можно требовать приличную выборку, а за
# месяц на сервере набирается ~16 сделок на все концепты - с порогом 20 месячный
# пост был бы пуст всегда.
CONCEPT_MIN_SAMPLE = 20
CONCEPT_MIN_SAMPLE_MONTH = 10

RE_TRADE_RR = re.compile(r'(?<![\w.])([+-]?\d+(?:[.,]\d+)?)\s*(?:rr|r\b)', re.IGNORECASE)
RE_TRADE_PCT = re.compile(r'([+-]\d+(?:[.,]\d+)?)\s*%')
RE_TRADE_BE = re.compile(r'\bbe\b|безубыт', re.IGNORECASE)
RE_TRADE_SL = re.compile(r'\bsl\b|\bstop\b|стоп', re.IGNORECASE)
RE_TRADE_TP = re.compile(r'\btp\b|\btake\b|тейк', re.IGNORECASE)


def classify_trade(title):
    """Заголовок треда -> ('win'|'loss'|'be'|None, размер в R или None)."""
    t = (title or "").lower()
    rr = None
    m = RE_TRADE_RR.search(t) or RE_TRADE_PCT.search(t)
    if m:
        try:
            rr = float(m.group(1).replace(",", "."))
        except ValueError:
            rr = None
    if RE_TRADE_BE.search(t) or (rr is not None and rr == 0):
        return "be", 0.0
    if RE_TRADE_SL.search(t) or (rr is not None and rr < 0):
        return "loss", -abs(rr) if rr is not None else None
    if RE_TRADE_TP.search(t) or (rr is not None and rr > 0):
        return "win", abs(rr) if rr is not None else None
    return None, None


async def all_trade_threads(guild):
    """Все треды обоих торговых форумов, активные и архивные."""
    out = []
    for cid in (TEAM_TRADES_CHANNEL_ID, USER_TRADES_CHANNEL_ID):
        forum = guild.get_channel(cid)
        if forum is None:
            continue
        try:
            out.extend(forum.threads)
            async for t in forum.archived_threads(limit=None):
                out.append(t)
        except Exception as e:
            print(f"[concept-stats] не смог прочитать форум {cid}: {e}")
    return out


async def collect_concept_stats(guild, since=None):
    """{концепт: {win, loss, be, rr[]}}. since - считать только треды новее даты."""
    by_role = {rid: label for label, rid, _ in CONCEPTS.values()}
    stats, skipped = {}, {"unparsed": 0, "no_concept": 0}
    # сводка считается ОТДЕЛЬНО, по одной записи на сделку: суммировать корзины
    # концептов нельзя - человек с двумя концептами попал бы в итог дважды
    totals = {"win": 0, "loss": 0, "be": 0, "rr": []}
    for t in await all_trade_threads(guild):
        if since is not None and t.created_at and t.created_at < since:
            continue
        outcome, size = classify_trade(t.name)
        if outcome is None:
            skipped["unparsed"] += 1
            continue
        member = guild.get_member(t.owner_id) if t.owner_id else None
        if member is None:
            skipped["no_concept"] += 1
            continue
        labels = [by_role[r.id] for r in member.roles if r.id in by_role]
        if not labels:
            skipped["no_concept"] += 1
            continue
        totals[outcome] += 1
        if size is not None:
            totals["rr"].append(size)
        for label in labels:   # у кого несколько концептов - идёт в каждый свой
            s = stats.setdefault(label, {"win": 0, "loss": 0, "be": 0, "rr": []})
            s[outcome] += 1
            if size is not None:
                s["rr"].append(size)
    return stats, skipped, totals


def concept_stats_embed(stats, skipped, totals, title, period_note, min_sample=CONCEPT_MIN_SAMPLE):
    rows, thin = [], []
    for label, s in sorted(stats.items(), key=lambda kv: -(kv[1]["win"] + kv[1]["loss"] + kv[1]["be"])):
        n = s["win"] + s["loss"] + s["be"]
        if n < min_sample:
            thin.append(f"{label} ({n})")
            continue
        decided = s["win"] + s["loss"]
        wr = f"{s['win'] / decided * 100:.0f}%" if decided else "-"
        avg = f"{sum(s['rr']) / len(s['rr']):+.2f}R" if s["rr"] else "-"
        rows.append(f"**{label}** - {n} сделок · винрейт {wr} · средняя {avg}"
                    + (f" · BE {s['be']}" if s["be"] else ""))
    desc = "\n".join(rows) if rows else "Ни один концепт пока не набрал выборку для отдельных выводов."
    if thin:
        desc += f"\n\n*Мало данных для выводов:* {', '.join(thin)}"

    # сводная строка по серверу: она осмысленна даже когда по концептам данных мало
    tw, tl, tb = totals["win"], totals["loss"], totals["be"]
    all_rr = totals["rr"]
    if tw + tl + tb:
        wr = f"{tw / (tw + tl) * 100:.0f}%" if (tw + tl) else "-"
        avg = f"{sum(all_rr) / len(all_rr):+.2f}R" if all_rr else "-"
        desc += (f"\n\n**Весь сервер** - {tw + tl + tb} сделок · винрейт {wr} · средняя {avg}"
                 + (f" · BE {tb}" if tb else ""))
    desc += (f"\n\n{period_note}\nИсход берётся из заголовка сделки (TP/SL/BE и RR). "
             f"Не распознано: {skipped['unparsed']}.\n"
             f"*Считаются выложенные сделки. Слитые выкладывают реже удачных, "
             f"поэтому цифры выше реальных.*")
    embed = discord.Embed(title=title, description=desc, color=0xd7ecff)
    embed.set_footer(text=f"Порог публикации - {min_sample} сделок. "
                          "Считаем трейдеров концепта, а не сам метод")
    return embed


@bot.slash_command(name="conceptstats", description="Статистика сделок по концептам (админ)")
@discord.default_permissions(administrator=True)
async def conceptstats(ctx, период: discord.Option(str, choices=["всё время", "этот месяц"]) = "всё время"):
    await ctx.defer(ephemeral=True)
    since = None
    note = "За всё время."
    min_sample = CONCEPT_MIN_SAMPLE
    if период == "этот месяц":
        now = datetime.now(PRAGUE)
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        note = f"За {now.strftime('%m.%Y')}."
        min_sample = CONCEPT_MIN_SAMPLE_MONTH
    stats, skipped, totals = await collect_concept_stats(ctx.guild, since)
    embed = concept_stats_embed(stats, skipped, totals, f"{E_LOGO} Концепты - результаты", note, min_sample)
    await ctx.respond("Опубликовано", ephemeral=True)
    await ctx.send(embed=embed)


# ==================================================================
#                      ЛИГА КОНЦЕПТОВ
# ==================================================================
# Команда - это концепт. Счёт - СРЕДНИЙ вклад участника за сезон, а не сумма:
# составы отличаются втрое (60 против 21), и по сумме крупнейший концепт был бы
# чемпионом всегда, независимо от того, что делают люди.
#
# Считаем вклад в R, а не винрейт. Винрейт как цель заставил бы выкладывать
# только удачные сделки, а разбор слитой полезнее сообществу, чем ещё один плюс.
LEAGUE_MIN_ROSTER = 5        # состав меньше этого в зачёт не идёт

# Метка чемпиона сезона вешается на РОЛЬ КОНЦЕПТА-победителя, а не выдаётся
# отдельной ролью: лигу выигрывает команда, поэтому знак носят все её участники,
# и он переходит сам. Пустая строка отключает механику целиком.
CHAMPION_MARK = "🦅"


def collect_league(guild, period="month"):
    """[(концепт, средний вклад, активных, состав, сумма R)] по убыванию счёта."""
    by_role = {rid: label for label, rid, _ in CONCEPTS.values()}
    teams = {}
    for member in guild.members:
        if member.bot or is_no_points(member) or is_service(member):
            continue
        labels = [by_role[r.id] for r in member.roles if r.id in by_role]
        if not labels:
            continue
        earned = points.get(member.id, {}).get(period, 0)
        for label in labels:
            t = teams.setdefault(label, {"roster": 0, "total": 0, "active": 0})
            t["roster"] += 1
            t["total"] += earned
            if earned > 0:
                t["active"] += 1
    rows = []
    for label, t in teams.items():
        if t["roster"] < LEAGUE_MIN_ROSTER:
            continue
        rows.append((label, t["total"] / t["roster"], t["active"], t["roster"], t["total"]))
    rows.sort(key=lambda r: -r[1])
    return rows


def league_embed(rows, title, period_note):
    if not rows:
        desc = "Пока не набралось данных для таблицы."
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (label, avg, active, roster, total) in enumerate(rows):
            mark = medals[i] if i < 3 else "▫️"
            share = f"{active / roster * 100:.0f}%"
            lines.append(f"{mark} **{label}** - {avg:.1f} {E_R} на участника\n"
                         f"　　активны {active} из {roster} ({share}) · всего {total} R")
        desc = "\n".join(lines)
    embed = discord.Embed(title=title, description=desc + f"\n\n{period_note}", color=0xd7ecff)
    embed.set_footer(text="Счёт - средний вклад участника, чтобы крупный состав "
                          "не выигрывал одним размером")
    return embed


async def move_champion_mark(guild, winner_label):
    """Снять метку с прошлого чемпиона и повесить новому."""
    if not CHAMPION_MARK:
        return
    for label, role_id, _ in CONCEPTS.values():
        role = guild.get_role(role_id)
        if role is None:
            continue
        base = role.name.replace(CHAMPION_MARK, "").strip()
        want = f"{base} {CHAMPION_MARK}" if label == winner_label else base
        if role.name != want:
            try:
                await role.edit(name=want, reason="чемпион сезона лиги концептов")
            except Exception as e:
                print(f"[league] не смог переименовать {role.name}: {e}")


@bot.slash_command(name="digest", description="Сводка недели прямо сейчас (админ)")
@discord.default_permissions(administrator=True)
async def digest(ctx):
    await ctx.defer(ephemeral=True)
    await post_weekly_digest(ctx.guild, f"по состоянию на {datetime.now(PRAGUE):%d.%m}", reset=False)
    await ctx.respond("Сводка отправлена в админский канал", ephemeral=True)


@bot.slash_command(name="league", description="Таблица лиги концептов (админ)")
@discord.default_permissions(administrator=True)
async def league(ctx, период: discord.Option(str, choices=["этот месяц", "эта неделя", "всё время"]) = "этот месяц"):
    key = {"этот месяц": "month", "эта неделя": "week", "всё время": "all"}[период]
    rows = collect_league(ctx.guild, key)
    note = {"month": f"Сезон {datetime.now(PRAGUE):%m.%Y}.",
            "week": "Текущая неделя.",
            "all": "За всё время."}[key]
    embed = league_embed(rows, f"{E_EAGLE} Лига концептов", note)
    await ctx.respond("Опубликовано", ephemeral=True)
    await ctx.send(embed=embed)


# ==================================================================
#                  НЕДЕЛЬНАЯ СВОДКА ДЛЯ КОМАНДЫ
# ==================================================================
# Отвечает на то, чего не знает ни один сторонний бот статистики: прошли ли
# новички гейт, кто из активных затих, что покупают за R и как двигается лига.
QUIET_AFTER_DAYS = 10        # столько дней молчания = «затих»
QUIET_MIN_EARNED = 30        # и при этом человек успел что-то дать сообществу

# счётчики недели живут в runtime_state и обнуляются после публикации
week_stats = {"joins": 0, "leaves": 0, "gate_passed": 0, "spent": 0, "purchases": 0}


def plural(n, one, few, many):
    """1 покупку / 2 покупки / 5 покупок"""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def bump_week(key, amount=1):
    week_stats[key] = week_stats.get(key, 0) + amount
    save_runtime_state()


def touch_seen(uid):
    """Отметить, что человек что-то сделал. Нужно для поиска затихших."""
    rec = points.get(uid)
    if rec is not None:
        rec["seen"] = datetime.now(timezone.utc).isoformat()


def quiet_members(guild):
    """Те, кто заметно вкладывался, а теперь молчит."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=QUIET_AFTER_DAYS)
    out = []
    for uid, rec in points.items():
        if rec.get("all", 0) < QUIET_MIN_EARNED:
            continue
        seen = rec.get("seen")
        if not seen:
            continue          # не видели с момента ввода отметки - судить рано
        try:
            when = datetime.fromisoformat(seen)
        except Exception:
            continue
        if when >= cutoff:
            continue
        member = guild.get_member(uid)
        if member is None or is_no_points(member):
            continue
        out.append((member, rec.get("all", 0), (datetime.now(timezone.utc) - when).days))
    out.sort(key=lambda x: -x[1])
    return out


async def weekly_forum_activity(guild, since):
    """Сколько тредов появилось за неделю в каждом форуме."""
    counts = {}
    forums = {"team-trades": TEAM_TRADES_CHANNEL_ID, "user-trades": USER_TRADES_CHANNEL_ID,
              "premarkets": PREMARKETS_CHANNEL_ID, "backtests": BACKTESTS_CHANNEL_ID}
    for name, cid in forums.items():
        forum = guild.get_channel(cid)
        if forum is None:
            continue
        n = 0
        try:
            for t in forum.threads:
                if t.created_at and t.created_at >= since:
                    n += 1
            async for t in forum.archived_threads(limit=50):
                if t.created_at and t.created_at >= since:
                    n += 1
        except Exception as e:
            print(f"[digest] форум {name}: {e}")
        counts[name] = n
    return counts


async def post_weekly_digest(guild, week_label, reset=True):
    channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if channel is None:
        return
    since = datetime.now(timezone.utc) - timedelta(days=7)

    gate = guild.get_role(GATE_ROLE_ID)
    gated = len([m for m in gate.members if not m.bot and not is_service(m)]) if gate else 0
    joins, leaves = week_stats.get("joins", 0), week_stats.get("leaves", 0)
    passed = week_stats.get("gate_passed", 0)

    earned = sum(r.get("week", 0) for r in points.values())
    spent = week_stats.get("spent", 0)
    purchases = week_stats.get("purchases", 0)

    forums = await weekly_forum_activity(guild, since)
    quiet = quiet_members(guild)
    league = collect_league(guild, "week")

    lines = [
        f"**Люди** · пришло {joins}, ушло {leaves}, итог {joins - leaves:+d}",
        f"**Воронка** · прошли гейт за неделю: {passed} · сидят в гейте сейчас: {gated}",
        f"**Экономика** · заработано {earned} {E_R}, потрачено {spent} "
        f"за {purchases} {plural(purchases, 'покупку', 'покупки', 'покупок')}",
    ]
    if forums:
        alive = " · ".join(f"{k} {v}" for k, v in forums.items())
        lines.append(f"**Форумы за неделю** · {alive}")

    def _in_week(ts):
        try:
            return datetime.fromisoformat(ts) >= since
        except Exception:
            return False
    dec_open = sum(1 for r in declared.values() if _in_week(r.get("opened_at", "")))
    dec_closed = sum(1 for r in declared.values() if _in_week(r.get("closed_at", "")))
    if dec_open or dec_closed:
        lines.append(f"**Заявки /trade** · открыто {dec_open}, закрыто {dec_closed}")
    if league:
        top = league[0]
        lines.append(f"**Лига недели** · ведёт {top[0]} - {top[1]:.1f} R на участника")

    # ритуал открытия: без этой строки понять, зашло или нет, можно только вручную
    active_streaks = [v for v in session_state.values() if v.get("streak", 0) > 0]
    ever = [v for v in session_state.values() if v.get("total", 0) > 0]
    if ever:
        best = max((v.get("streak", 0) for v in session_state.values()), default=0)
        lines.append(f"**Открытия сессии** · ходят регулярно {len(active_streaks)} "
                     f"из {len(ever)} отметившихся когда-либо · лучшая серия {best}")
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    echoed_week = sum(1 for ts in echoed_threads.values() if not _ts_before(ts, week_ago))
    if echoed_week:
        lines.append(f"**Эхо** · поднято записей за неделю: {echoed_week}")

    embed = discord.Embed(title=f"📋 Сводка недели - {week_label}",
                          description="\n".join(lines), color=0xd7ecff)

    if quiet:
        text = "\n".join(f"{m.mention} - {total} R за всё время, "
                         f"молчит {days} {plural(days, 'день', 'дня', 'дней')}"
                         for m, total, days in quiet[:8])
        embed.add_field(name=f"Затихли ({len(quiet)}) - стоит написать", value=text, inline=False)
    else:
        embed.add_field(name="Затихшие", value="Никого: активные на месте.", inline=False)

    zero = [k for k, v in forums.items() if v == 0]
    if zero:
        embed.add_field(name="Тишина в форумах",
                        value="За неделю ни одного поста: " + ", ".join(zero), inline=False)

    embed.set_footer(text="Считается по данным бота: R, роли, форумы. "
                          "«Затих» - не появлялся в начислениях 10 дней подряд")
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=False))
    except Exception as e:
        print(f"[digest] не отправилась: {e}")
    if reset:                 # ручной вызов не должен ломать недельный цикл
        for k in week_stats:
            week_stats[k] = 0
        save_runtime_state()


# ==================================================================
#                    ДЕТЕКТОР ЗАХОДА ПАЧКОЙ
# ==================================================================
# Пороги выставлены по истории сервера: пачки по 3-7 человек - обычное дело
# (медианный возраст аккаунта при заходе 1669 дней, то есть живые люди), а
# единственный выброс за полгода - 15 заходов с 9 свежими аккаунтами.
# На этой истории правило срабатывает ровно один раз, ложных нет.
RAID_WINDOW_MIN = 30      # окно наблюдения
RAID_MIN_JOINS = 5        # столько заходов в окне, чтобы вообще смотреть
RAID_MIN_YOUNG = 3        # и столько из них свежими аккаунтами
RAID_YOUNG_DAYS = 10      # аккаунт моложе этого считается свежим
RAID_COOLDOWN_MIN = 60    # не повторять тревогу по той же волне

recent_joins = deque()    # (время, uid, имя, возраст аккаунта в днях)


async def note_join_and_check(member):
    """Записать заход и поднять тревогу, если пачка выглядит закупкой."""
    now = datetime.now(timezone.utc)
    age = (now - member.created_at).days
    recent_joins.append((now, member.id, member.name, age))
    while recent_joins and (now - recent_joins[0][0]) > timedelta(minutes=RAID_WINDOW_MIN):
        recent_joins.popleft()

    if len(recent_joins) < RAID_MIN_JOINS:
        return
    young = [j for j in recent_joins if j[3] < RAID_YOUNG_DAYS]
    if len(young) < RAID_MIN_YOUNG:
        return          # пачка живых людей - это хороший день, а не тревога
    last = once_marks.get("raid_alert")
    if last:
        try:
            if (now - datetime.fromisoformat(last)) < timedelta(minutes=RAID_COOLDOWN_MIN):
                return
        except Exception:
            pass
    once_marks["raid_alert"] = now.isoformat()
    save_runtime_state()

    ch = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if ch is None:
        return
    lines = [f"· {name} - аккаунту {age} {plural(age, 'день', 'дня', 'дней')}"
             for _, _, name, age in sorted(young, key=lambda j: j[3])[:12]]
    embed = discord.Embed(
        title="⚠️ Заход пачкой свежими аккаунтами",
        description=(f"За {RAID_WINDOW_MIN} минут зашло **{len(recent_joins)}**, "
                     f"из них **{len(young)}** с аккаунтами моложе "
                     f"{RAID_YOUNG_DAYS} дней.\n\n" + "\n".join(lines)),
        color=0xffaa33)
    embed.set_footer(text="Если это ваша закупка бустов - просто проигнорируйте. "
                          "Если нет, стоит проверить инвайты")
    try:
        await ch.send(embed=embed)
    except Exception as e:
        print(f"[raid] тревога не ушла: {e}")


# ==================================================================
#                    ОТКРЫТИЕ СЕССИИ
# ==================================================================
# Войс - самая живая механика сервера: 1373 часа против 111 постов в форумах,
# и до сих пор она не была отмечена ничем, кроме 1 R в час. Ритуал открытия
# даёт ей повод, счёт и серию, которую жалко обрывать.
#
# Время считается ОТ НЬЮ-ЙОРКА, а не зашивается по европейскому: в марте переходы
# летнее время расходятся и открытие уезжает на 14:30.
SESSION_CHANNEL_ID = NEWS_CHANNEL_ID
SESSION_STATE_FILE = "session_state.json"
SESSION_OPEN = (9, 30)          # 9:30 ET
SESSION_BEFORE_MIN = 15         # за сколько минут собираем
SESSION_AFTER_MIN = 30          # сколько ещё считаем явку после открытия
SESSION_STREAK_BONUS = {5: 10, 10: 25, 20: 60, 50: 150}   # серия -> разовый R

session_state = {}   # uid(str) -> {"streak", "best", "last", "total"}
# Прогресс дня лежит в том же файле, а не только в памяти: рестарт внутри окна
# публиковал бриф второй раз и терял уже отмеченную явку.
session_day = {}     # {"day", "announced", "settled", "present": [uid]}


def load_session_state():
    global session_state, session_day
    if os.path.exists(SESSION_STATE_FILE):
        try:
            with open(SESSION_STATE_FILE, "r") as f:
                data = json.load(f)
            session_state = data.get("members", data)      # старый формат - плоский
            session_day = data.get("day_progress", {})
        except Exception as e:
            print(f"session state load error: {e}")
            session_state, session_day = {}, {}


def save_session_state():
    save_json_atomic(SESSION_STATE_FILE,
                     {"members": session_state, "day_progress": session_day},
                     "session state")


def ny_open_today(now_ny):
    return now_ny.replace(hour=SESSION_OPEN[0], minute=SESSION_OPEN[1],
                          second=0, microsecond=0)


def session_window(now_ny):
    """(начало, открытие, конец) окна сегодняшней сессии."""
    op = ny_open_today(now_ny)
    return op - timedelta(minutes=SESSION_BEFORE_MIN), op, op + timedelta(minutes=SESSION_AFTER_MIN)


def streak_line(uid):
    rec = session_state.get(str(uid))
    if not rec or not rec.get("streak"):
        return None
    s = rec["streak"]
    return f"{s} {plural(s, 'день', 'дня', 'дней')} подряд"


async def announce_session(channel, now_ny):
    """Бриф перед открытием: во сколько, что сегодня выходит, кто уже в войсе."""
    events = [e for e in usd_events() if e["dt"].date() == datetime.now(PRAGUE).date()
              and e["dt"] > datetime.now(PRAGUE)]
    events.sort(key=lambda e: e["dt"])
    lines = [f"Нью-Йорк открывается в **{ny_open_today(now_ny).astimezone(PRAGUE):%H:%M}** по Европе."]
    if events:
        lines.append("")
        lines.append("**Сегодня ещё выходит:**")
        for e in events[:4]:
            lines.append(f"· {e['dt_ny']:%H:%M} NY · {e['dt'].astimezone(PRAGUE):%H:%M} EU "
                         f"{impact_emoji(e['impact'])} {e['title']}"
                         + (f" · прогноз {e['forecast']}" if e["forecast"] else ""))
    else:
        lines.append("Важных выходов по США на остаток дня нет.")

    in_voice = [uid for uid in voice_join_times]
    if in_voice:
        lines.append("")
        lines.append(f"В войсе уже {len(in_voice)} "
                     f"{plural(len(in_voice), 'человек', 'человека', 'человек')}.")

    top = sorted(((v.get("streak", 0), k) for k, v in session_state.items()), reverse=True)[:3]
    top = [(s, k) for s, k in top if s >= 3]
    if top:
        guild = channel.guild
        parts = []
        for s, uid in top:
            m = guild.get_member(int(uid))
            if m:
                parts.append(f"{m.display_name} - {s}")
        if parts:
            lines.append("")
            lines.append("**Длинные серии:** " + " · ".join(parts))

    embed = discord.Embed(title=f"{E_EAGLE} Открытие сессии", description="\n".join(lines),
                          color=0xd7ecff)
    embed.set_footer(text="Заходи в войс до конца окна - день засчитается в серию. "
                          "Сделку на день можно заявить: /trade")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[session] бриф не ушёл: {e}")


async def settle_session(channel, day):
    """Закрыть окно: обновить серии, выдать бонусы за вехи."""
    joined, broke, bonuses = [], 0, []
    present = {int(u) for u in session_day.get("present", [])}
    known = set(session_state.keys()) | {str(u) for u in present}
    for uid in known:
        rec = session_state.setdefault(uid, {"streak": 0, "best": 0, "last": "", "total": 0})
        if int(uid) in present:
            if rec.get("last") == day:
                continue                      # уже засчитан сегодня
            rec["streak"] = rec.get("streak", 0) + 1
            rec["total"] = rec.get("total", 0) + 1
            rec["best"] = max(rec.get("best", 0), rec["streak"])
            rec["last"] = day
            joined.append(uid)
            bonus = SESSION_STREAK_BONUS.get(rec["streak"])
            if bonus:
                member = channel.guild.get_member(int(uid))
                if member:
                    add_points(member, bonus)
                    bonuses.append((member, rec["streak"], bonus))
        elif rec.get("streak", 0) > 0:
            rec["streak"] = 0                 # пропустил торговый день - серия сброшена
            broke += 1
    save_session_state()

    if not joined and not bonuses:
        return
    lines = [f"Отметились: **{len(joined)}** "
             f"{plural(len(joined), 'человек', 'человека', 'человек')}."]
    if broke:
        lines.append(f"Серия оборвалась у {broke}.")
    for member, streak, bonus in bonuses:
        lines.append(f"🔥 {member.mention} - {streak} "
                     f"{plural(streak, 'день', 'дня', 'дней')} подряд, +{bonus} {E_R}")
    embed = discord.Embed(title="Сессия открыта", description="\n".join(lines), color=0xd7ecff)
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=False))
    except Exception as e:
        print(f"[session] итог не ушёл: {e}")


@tasks.loop(minutes=1)
@loop_guard("session")
async def session_loop():
    now_ny = datetime.now(NEWYORK)
    if now_ny.weekday() >= 5:
        return                                # выходные бирже не считаются
    start, op, end = session_window(now_ny)
    day = now_ny.date().isoformat()
    channel = bot.get_channel(SESSION_CHANNEL_ID)
    if channel is None:
        return

    if session_day.get("day") != day:         # новый день - начинаем заново
        session_day.clear()
        session_day.update({"day": day, "announced": False,
                            "settled": False, "present": []})
        save_session_state()

    if start <= now_ny <= end:
        present = set(session_day.get("present", [])) | set(voice_join_times.keys())
        if present != set(session_day.get("present", [])):
            session_day["present"] = sorted(present)
            save_session_state()
        if not session_day.get("announced") and now_ny <= op:
            if not feed_cache:
                return        # календарь ещё не загружен - лучше подождать минуту,
                              # чем объявить «событий нет», не зная этого
            session_day["announced"] = True
            save_session_state()
            await announce_session(channel, now_ny)
    elif now_ny > end and session_day.get("announced") and not session_day.get("settled"):
        session_day["settled"] = True
        save_session_state()
        await settle_session(channel, day)


# ==================================================================
#                            ЭХО
# ==================================================================
# Бот поднимает старую запись автора и спрашивает, что из неё вышло.
# Ресёрч по удержанию сообществ сходится на одном: живут те, где спрашивают за
# процесс, а не за результат. Но механики под это нет ни у кого - есть только
# пожелание «ведите дневник». Эхо превращает пожелание в то, что происходит само.
#
# Эхо работает по любому настроенному форуму. Сейчас материал есть только в
# торговых (51 запись возрастом около месяца), премаркеты стоят с 13 июля -
# если они оживут, эхо подхватит их без правок.
ECHO_HOUR = 20              # час по европейскому времени
ECHO_AGE_DAYS = 30          # какого возраста запись поднимаем
ECHO_AGE_SPREAD = 5         # допуск в днях
ECHO_PER_DAY = 2            # больше - это уже спам в старых тредах
ECHO_KEEP_DAYS = 400        # сколько помним, что уже поднимали

ECHO_TEXTS = {
    "trade": "Месяц назад ты выложил эту сделку. Глядя назад - вошёл бы так же?",
    "premarket": "Месяц назад это был твой план на день. Что из него сработало?",
    "backtest": "Месяц назад ты это тестировал. Пригодилось в реальных сделках?",
}
ECHO_FORUMS = {}            # заполняется в on_ready: id форума -> тип текста

echoed_threads = {}         # id треда -> когда подняли


def echo_kind(parent_id):
    return ECHO_FORUMS.get(parent_id, "trade")


async def collect_echo_candidates(guild):
    """Треды нужного возраста, которые ещё не поднимали и чей автор на месте."""
    now = datetime.now(timezone.utc)
    lo = now - timedelta(days=ECHO_AGE_DAYS + ECHO_AGE_SPREAD)
    hi = now - timedelta(days=ECHO_AGE_DAYS - ECHO_AGE_SPREAD)
    out = []
    for cid in ECHO_FORUMS:
        forum = guild.get_channel(cid)
        if forum is None:
            continue
        try:
            threads = list(forum.threads)
            async for t in forum.archived_threads(limit=100):
                threads.append(t)
        except Exception as e:
            print(f"[echo] форум {cid}: {e}")
            continue
        for t in threads:
            if str(t.id) in echoed_threads:
                continue
            if not t.created_at or not (lo <= t.created_at <= hi):
                continue
            if not t.owner_id:
                continue
            member = guild.get_member(t.owner_id)
            if member is None or member.bot:
                continue        # автор ушёл - поднимать нечего и некому
            out.append((t, member))
    out.sort(key=lambda x: x[0].created_at)
    return out


async def send_echo(thread, member):
    kind = echo_kind(thread.parent_id)
    text = ECHO_TEXTS.get(kind, ECHO_TEXTS["trade"])
    embed = discord.Embed(description=f"{member.mention}, {text}", color=0xd7ecff)
    embed.set_footer(text="Эхо · бот поднимает записи месячной давности")
    try:
        # unarchive, иначе ответ в архивный тред не уйдёт
        if getattr(thread, "archived", False):
            await thread.edit(archived=False)
        await thread.send(embed=embed)
        echoed_threads[str(thread.id)] = datetime.now(timezone.utc).isoformat()
        save_runtime_state()
        print(f"[echo] поднят тред {thread.id} ({thread.name[:40]})")
        return True
    except Exception as e:
        print(f"[echo] не смог поднять {thread.id}: {e}")
        echoed_threads[str(thread.id)] = datetime.now(timezone.utc).isoformat()
        save_runtime_state()     # не долбимся в него каждый день
        return False


@tasks.loop(minutes=10)
@loop_guard("echo")
async def echo_loop():
    now = datetime.now(PRAGUE)
    if now.hour != ECHO_HOUR:
        return
    day = now.date().isoformat()
    if once_marks.get("echo_day") == day:
        return
    once_marks["echo_day"] = day
    save_runtime_state()
    prune_dedup(echoed_threads, days=ECHO_KEEP_DAYS)
    for guild in bot.guilds:
        cands = await collect_echo_candidates(guild)
        if not cands:
            continue
        for thread, member in cands[:ECHO_PER_DAY]:
            await send_echo(thread, member)
            await asyncio.sleep(2)


# ==================================================================
#                        СЛЕПОЙ ГРАФИК
# ==================================================================
# Раз в неделю бот берёт РЕАЛЬНЫЙ кусок истории по инструменту, который тут
# торгуют, рисует свечи и обрезает правый край. Участники ставят R на то, куда
# ушла цена. Ответ известен заранее - он в тех же данных, поэтому вскрытие не
# зависит ни от какого внешнего запроса в будущем.
#
# Расчёт идёт тем же тотализатором, что и ставки на макроданные.
BLIND_CHANNEL_ID = NEWS_CHANNEL_ID
BLIND_STATE_FILE = "blind_state.json"
BLIND_DAY = 2                 # среда
BLIND_HOUR = 18               # час по европейскому времени
BLIND_REVEAL_HOURS = 24
BLIND_VISIBLE = 60            # сколько свечей показываем
BLIND_HIDDEN = 5              # сколько прячем - на них и ставят
BLIND_STAKES = [5, 10, 25]
# Из чего выбираем новые задачи
BLIND_INSTRUMENTS = {
    "NQ=F": "Nasdaq 100",
    "ES=F": "S&P 500",
    "GC=F": "Золото",
}
# Названия для показа. Шире списка выбора: уже идущая игра могла быть создана на
# инструменте, который потом убрали из ротации, и при вскрытии он должен
# называться по-человечески, а не тикером
BLIND_NAMES = dict(BLIND_INSTRUMENTS, **{"CL=F": "Нефть WTI"})

blind_state = {}   # msg_id -> {instrument, answer, ref, bets:{uid:{side,amount}}, reveal_at, settled}


def load_blind_state():
    global blind_state
    if os.path.exists(BLIND_STATE_FILE):
        try:
            with open(BLIND_STATE_FILE, "r") as f:
                blind_state = json.load(f)
        except Exception as e:
            print(f"blind state load error: {e}")
            blind_state = {}


def save_blind_state():
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    for mid in [m for m, b in list(blind_state.items()) if b.get("settled")]:
        try:
            if datetime.fromisoformat(blind_state[mid]["reveal_at"]) < cutoff:
                del blind_state[mid]
        except Exception:
            del blind_state[mid]
    save_json_atomic(BLIND_STATE_FILE, blind_state, "blind state")


async def fetch_candles(ticker, rng="2y", interval="1d"):
    """Свечи с Yahoo. Без ключа и без сторонних библиотек."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rng}&interval={interval}")
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
            data = await r.json(content_type=None)
    res = data["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue          # у Yahoo попадаются дыры
        out.append((ts, o, h, l, c))
    return out


def render_chart(candles, title):
    """Свечи в PNG. Правый край уже обрезан вызывающим."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6), dpi=110)
    fig.patch.set_facecolor("#0e1621")
    ax.set_facecolor("#0e1621")
    up, down = "#4CBF8B", "#E0705F"
    for i, (_ts, o, h, l, c) in enumerate(candles):
        col = up if c >= o else down
        ax.plot([i, i], [l, h], color=col, linewidth=0.9, solid_capstyle="round")
        ax.add_patch(plt.Rectangle((i - 0.32, min(o, c)), 0.64, abs(c - o) or (h - l) * 0.002,
                                   facecolor=col, edgecolor=col, linewidth=0.5))
    ax.set_title(title, color="#E8EFF6", fontsize=14, pad=14, loc="left")
    ax.grid(color="#1e2a38", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color("#27333F")
    ax.tick_params(colors="#8593A2", labelsize=9)
    ax.set_xticks([])
    ax.margins(x=0.01)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


async def build_blind_setup():
    """Случайный инструмент и окно истории -> (картинка, инструмент, ответ, опора)."""
    ticker = random.choice(list(BLIND_INSTRUMENTS))
    candles = await fetch_candles(ticker)
    need = BLIND_VISIBLE + BLIND_HIDDEN
    if len(candles) < need + 10:
        return None
    start = random.randint(0, len(candles) - need - 1)
    visible = candles[start:start + BLIND_VISIBLE]
    hidden = candles[start + BLIND_VISIBLE:start + need]
    ref = visible[-1][4]                    # последнее видимое закрытие
    final = hidden[-1][4]
    answer = "up" if final > ref else "down"
    change = (final - ref) / ref * 100
    # matplotlib синхронный и держит event loop до секунды - у Discord окно
    # ответа на взаимодействие всего 3 с, поэтому рисуем в отдельном потоке
    img = await asyncio.to_thread(render_chart, visible,
                                  f"{BLIND_INSTRUMENTS[ticker]}  ·  дневные свечи")
    return img, ticker, answer, ref, change


class BlindButton(discord.ui.Button):
    def __init__(self, side, amount):
        arrow = "▲" if side == "up" else "▼"
        super().__init__(label=f"{arrow} {amount} R", style=discord.ButtonStyle.secondary,
                         custom_id=f"blind_{side}_{amount}",
                         row=0 if side == "up" else 1)
        self.side, self.amount = side, amount

    async def callback(self, interaction: discord.Interaction):
        mid = str(interaction.message.id)
        game = blind_state.get(mid)
        if game is None or game.get("settled"):
            await interaction.response.send_message("Приём ставок закрыт.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if uid in game["bets"]:
            old = game["bets"][uid]
            where = "вверх" if old["side"] == "up" else "вниз"
            await interaction.response.send_message(
                f"Ты уже поставил {old['amount']} R на «{where}». Одна ставка на график.",
                ephemeral=True)
            return
        if not spend(interaction.user.id, self.amount):
            await interaction.response.send_message(
                f"Не хватает R: нужно {self.amount}, у тебя {balance(interaction.user.id)}.",
                ephemeral=True)
            return
        game["bets"][uid] = {"side": self.side, "amount": self.amount}
        save_blind_state()
        pool = sum(b["amount"] for b in game["bets"].values())
        where = "вверх" if self.side == "up" else "вниз"
        await interaction.response.send_message(
            f"Принято: {self.amount} R на «{where}».\nВ банке {pool} R, "
            f"ставок {len(game['bets'])}. Остаток: {balance(interaction.user.id)} R.",
            ephemeral=True)


class BlindView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for side in ("up", "down"):
            for amount in BLIND_STAKES:
                self.add_item(BlindButton(side, amount))


async def post_blind_chart(channel):
    try:
        setup = await build_blind_setup()
    except Exception as e:
        print(f"[blind] не смог собрать задачу: {type(e).__name__}: {e}")
        return False
    if setup is None:
        print("[blind] не хватило данных")
        return False
    img, ticker, answer, ref, change = setup
    reveal = datetime.now(timezone.utc) + timedelta(hours=BLIND_REVEAL_HOURS)
    embed = discord.Embed(
        title=f"{E_EAGLE} Слепой график",
        description=(f"Реальный кусок истории. Правый край скрыт: **{BLIND_HIDDEN} свечей**.\n"
                     f"Куда ушла цена от последнего закрытия?\n\n"
                     f"Номиналы: {', '.join(str(s) for s in BLIND_STAKES)} {E_R}. "
                     f"Одна ставка. Вскрытие через {BLIND_REVEAL_HOURS} ч."),
        color=0xd7ecff)
    embed.set_image(url="attachment://chart.png")
    embed.set_footer(text="Инструмент и период не подсказываем намеренно")
    msg = await channel.send(embed=embed, file=discord.File(img, "chart.png"), view=BlindView())
    blind_state[str(msg.id)] = {
        "instrument": ticker, "answer": answer, "ref": ref, "change": change,
        "bets": {}, "reveal_at": reveal.isoformat(), "settled": False,
        "channel_id": channel.id,
    }
    save_blind_state()
    print(f"[blind] выложен график {ticker}, ответ {answer}")
    return True


async def settle_blind(mid, game):
    game["settled"] = True
    channel = bot.get_channel(game.get("channel_id") or BLIND_CHANNEL_ID)
    players = game["bets"]
    answer = game["answer"]
    where = "вверх" if answer == "up" else "вниз"
    head = (f"Инструмент: **{BLIND_NAMES.get(game['instrument'], game['instrument'])}**\n"
            f"Цена ушла **{where}** на {abs(game['change']):.2f}% за {BLIND_HIDDEN} свечей.")
    if not players:
        desc = head + "\n\nСтавок не было."
    else:
        payouts = parimutuel_payout(players, answer)
        for uid, _stake, share in payouts:
            credit(uid, share)
        pool = sum(b["amount"] for b in players.values())
        if not payouts:
            desc = head + f"\n\nНикто не угадал. Банк {pool} {E_R} сгорел ({len(players)} ставок)."
        else:
            lines = [f"<@{u}> - ставил {st}, забрал {sh}" for u, st, sh in
                     sorted(payouts, key=lambda x: -x[2])[:10]]
            desc = (head + f"\n\nБанк {pool} {E_R} на {len(payouts)} угадавших "
                           f"из {len(players)}.\n\n" + "\n".join(lines))
    save_blind_state()
    if channel:
        embed = discord.Embed(title="🔍 Слепой график - вскрытие", description=desc, color=0xd7ecff)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=False))
        except Exception as e:
            print(f"[blind] вскрытие не ушло: {e}")


@tasks.loop(minutes=10)
@loop_guard("blind")
async def blind_loop():
    now = datetime.now(PRAGUE)
    # вскрытие тех, чей срок вышел
    for mid, game in list(blind_state.items()):
        if game.get("settled"):
            continue
        try:
            if datetime.fromisoformat(game["reveal_at"]) <= datetime.now(timezone.utc):
                await settle_blind(mid, game)
        except Exception as e:
            print(f"[blind] сбой вскрытия {mid}: {e}")
    # публикация раз в неделю
    week = now.strftime("%Y-W%W")
    if now.weekday() != BLIND_DAY or now.hour != BLIND_HOUR or once_marks.get("blind_week") == week:
        return
    channel = bot.get_channel(BLIND_CHANNEL_ID)
    if channel is None:
        return
    # неделю помечаем ТОЛЬКО после удачной публикации: иначе разовый сбой Yahoo
    # съедал бы весь недельный выпуск
    if await post_blind_chart(channel):
        once_marks["blind_week"] = week
        save_runtime_state()


# ==================================================================
#              ЗАЯВКА: сделка описывается ДО исхода
# ==================================================================
# Смысл механики в одном: решение «выкладывать или нет» принимается, когда
# исход ещё неизвестен. Пока оно принимается после, любая статистика сообщества
# завышена - выигрышные сделки выкладывают охотнее слитых, и никакая математика
# этого не исправит.
#
# Заявка встроена в существующий форум и его теги, а не живёт рядом: у форума
# теги обязательны и уже содержат TP/SL/BE, концепты и инструменты - это
# структурные данные, надёжнее разбора заголовков.
DECLARE_FORUM_ID = USER_TRADES_CHANNEL_ID
DECLARED_FILE = "declared_trades.json"
R_DECLARED_CLOSED = 25          # за закрытую заявку; свободный пост даёт 15
DECLARE_STALE_DAYS = 14         # после этого незакрытая заявка помечается брошенной
# Потолок результата. Смысл не в том, что 50R невозможны, а в том, что опечатка
# в цене выхода даёт сотни R и навсегда портит счёт сервера - а он и держится
# на том, что его цифрам можно верить. Лишний ноль во входе 20200 даёт +1818R.
DECLARE_MAX_R = 50

# name -> id тегов форума
DECLARE_TAGS = {
    "TP": env_id("DECLARE_TAG_TP"), "SL": env_id("DECLARE_TAG_SL"), "BE": env_id("DECLARE_TAG_BE"),
    "NQ": env_id("DECLARE_TAG_NQ"), "ES": env_id("DECLARE_TAG_ES"), "GC": env_id("DECLARE_TAG_GC"),
}
# концепт участника -> тег форума
CONCEPT_TAGS = {
    "MLTF": env_id("CONCEPT_TAG_MLTF"), "Market Profile": env_id("CONCEPT_TAG_MARKET_PROFILE"),
    "OrderFlow": env_id("CONCEPT_TAG_ORDERFLOW"), "Price Action": env_id("CONCEPT_TAG_PRICE_ACTION"),
    "Swing": env_id("CONCEPT_TAG_SWING"), "0DTE": env_id("CONCEPT_TAG_0DTE"),
}

declared = {}   # id заявки -> запись


def load_declared():
    global declared
    if os.path.exists(DECLARED_FILE):
        try:
            with open(DECLARED_FILE, "r") as f:
                declared = json.load(f)
        except Exception as e:
            print(f"declared load error: {e}")
            declared = {}


def save_declared():
    save_json_atomic(DECLARED_FILE, declared, "declared trades")


def parse_price(raw):
    try:
        return float(str(raw).strip().replace(",", ".").replace(" ", ""))
    except Exception:
        return None


def r_multiple(entry, stop, exit_price):
    """Во сколько R обошлась сделка. Риск - расстояние от входа до стопа."""
    risk = abs(entry - stop)
    if risk == 0:
        return None
    direction = 1 if stop < entry else -1        # стоп ниже входа => лонг
    return round((exit_price - entry) * direction / risk, 2)


def declare_tags(guild, member, instrument, outcome=None):
    """Теги для треда: инструмент, концепты автора и исход, если он уже известен."""
    tags = []
    inst = DECLARE_TAGS.get(instrument.upper())
    if inst:
        tags.append(inst)
    by_role = {rid: label for label, rid, _ in CONCEPTS.values()}
    for r in member.roles:
        t = CONCEPT_TAGS.get(by_role.get(r.id, ""))
        if t and t not in tags:
            tags.append(t)
    if outcome and DECLARE_TAGS.get(outcome):
        tags.append(DECLARE_TAGS[outcome])
    return tags[:5]                              # Discord разрешает максимум 5


def tag_objects(forum, ids):
    """id тегов -> объекты ForumTag.

    py-cord дёргает у элементов applied_tags атрибут .id, поэтому голые числа
    сюда передавать нельзя - падает AttributeError.
    """
    if forum is None:
        return []
    want = set(ids)
    return [t for t in getattr(forum, "available_tags", []) if t.id in want]


def declared_embed(rec, member):
    side = "LONG" if rec["stop"] < rec["entry"] else "SHORT"
    opened = datetime.fromisoformat(rec["opened_at"]).astimezone(PRAGUE)
    lines = [
        f"**{rec['instrument']} {side}**",
        f"вход **{rec['entry']}** · стоп **{rec['stop']}** · цель **{rec['target']}**",
        f"план: **{rec['planned_r']}R**",
    ]
    if rec.get("status") == "closed":
        res = rec["result_r"]
        mark = "🟢" if res > 0 else ("⚪" if res == 0 else "🔴")
        lines.append("")
        lines.append(f"{mark} закрыта по **{rec['exit']}** - результат **{res:+.2f}R**")
        closed = datetime.fromisoformat(rec["closed_at"]).astimezone(PRAGUE)
        lines.append(f"держал {(closed - opened).total_seconds() / 3600:.1f} ч")
    else:
        lines.append("")
        lines.append("Заявка открыта. Скрин графика кидай сюда же следующим сообщением.")
        lines.append("Закрой заявку кнопкой, когда выйдешь из сделки.")
    embed = discord.Embed(description="\n".join(lines), color=0xd7ecff)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_footer(text=f"Заявлено {opened:%d.%m %H:%M} · до того, как стал известен исход")
    return embed


class DeclareModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Заявка на сделку")
        self.add_item(discord.ui.InputText(label="Инструмент", placeholder="NQ, ES, GC", max_length=10))
        self.add_item(discord.ui.InputText(label="Вход", placeholder="20150"))
        self.add_item(discord.ui.InputText(label="Стоп", placeholder="20100"))
        self.add_item(discord.ui.InputText(label="Цель", placeholder="20250"))
        self.add_item(discord.ui.InputText(
            label=f"Ставка на дисциплину, {DBET_MIN}-{DBET_MAX} R (не обязательно)",
            placeholder="пусто = без ставки", required=False))

    async def callback(self, interaction: discord.Interaction):
        inst = self.children[0].value.strip().upper()[:10]
        dbet_raw = (self.children[4].value or "").strip()
        dbet = None
        if dbet_raw:
            try:
                dbet = int(dbet_raw)
            except ValueError:
                await interaction.response.send_message(
                    "Ставка на дисциплину должна быть целым числом R.", ephemeral=True)
                return
            if not (DBET_MIN <= dbet <= DBET_MAX):
                await interaction.response.send_message(
                    f"Ставка на дисциплину: от {DBET_MIN} до {DBET_MAX} R.", ephemeral=True)
                return
            if balance(interaction.user.id) < dbet:
                await interaction.response.send_message(
                    f"На ставку не хватает R: нужно {dbet}, у тебя "
                    f"{balance(interaction.user.id)}.", ephemeral=True)
                return
        entry, stop, target = (parse_price(self.children[i].value) for i in (1, 2, 3))
        if None in (entry, stop, target):
            await interaction.response.send_message(
                "Цены должны быть числами. Пример: 20150 или 20150.5", ephemeral=True)
            return
        if min(entry, stop, target) <= 0:
            await interaction.response.send_message(
                "Цены должны быть больше нуля. Проверь, всё ли ввёл.", ephemeral=True)
            return
        if entry == stop:
            await interaction.response.send_message(
                "Стоп не может совпадать со входом - тогда риск нулевой.", ephemeral=True)
            return
        long = stop < entry
        if (long and target <= entry) or (not long and target >= entry):
            await interaction.response.send_message(
                "Цель по ту же сторону от входа, что и стоп. Проверь числа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        planned = round(abs(target - entry) / abs(entry - stop), 2)
        forum = interaction.guild.get_channel(DECLARE_FORUM_ID)
        if forum is None:
            await interaction.followup.send("Форум сделок не найден, скажи админу", ephemeral=True)
            return

        side = "LONG" if long else "SHORT"
        rec = {"uid": member.id, "instrument": inst, "entry": entry, "stop": stop,
               "target": target, "planned_r": planned, "status": "open",
               "opened_at": datetime.now(timezone.utc).isoformat()}
        try:
            thread = await forum.create_thread(
                name=f"{inst} {side} · план {planned}R · {member.display_name}"[:100],
                content=None,
                embed=declared_embed(rec, member),
                applied_tags=tag_objects(forum, declare_tags(interaction.guild, member, inst)),
                view=DeclaredView(),
            )
        except Exception as e:
            print(f"[declare] не смог создать тред: {e}")
            await interaction.followup.send(f"Не получилось создать пост: {type(e).__name__}",
                                            ephemeral=True)
            return

        rec.update({"thread_id": thread.id, "message_id": thread.id})
        bet_note = ""
        if dbet and spend(member.id, dbet):
            rec["dbet"] = {"amt": dbet, "resolved": False}
            bet_note = (f"\nСтавка на дисциплину: **{dbet} R** заморожено. "
                        f"Доведёшь по правилам - вернётся с бонусом "
                        f"+{int(dbet * DBET_BONUS + 0.999)}.")
        declared[str(thread.id)] = rec
        save_declared()
        await interaction.followup.send(
            f"Заявка принята: {inst} {side}, план {planned}R.\n{thread.jump_url}\n"
            f"Скрин прикладывай прямо в треде.{bet_note}", ephemeral=True)


class CloseModal(discord.ui.Modal):
    def __init__(self, tid):
        super().__init__(title="Закрыть заявку")
        self.tid = tid
        self.add_item(discord.ui.InputText(label="Цена выхода", placeholder="20200"))

    async def callback(self, interaction: discord.Interaction):
        rec = declared.get(self.tid)
        if rec is None or rec.get("status") == "closed":
            await interaction.response.send_message("Заявка уже закрыта.", ephemeral=True)
            return
        price = parse_price(self.children[0].value)
        if price is None:
            await interaction.response.send_message("Цена должна быть числом.", ephemeral=True)
            return
        if price <= 0:
            await interaction.response.send_message(
                "Цена выхода должна быть больше нуля.", ephemeral=True)
            return
        res = r_multiple(rec["entry"], rec["stop"], price)
        if res is None:
            await interaction.response.send_message("Не смог посчитать результат.", ephemeral=True)
            return
        if abs(res) > DECLARE_MAX_R:
            await interaction.response.send_message(
                f"Получается {res:+.0f}R - это почти наверняка опечатка в цене.\n"
                f"Вход был {rec['entry']}, стоп {rec['stop']}. Проверь и введи заново.",
                ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        rec.update({"status": "closed", "exit": price, "result_r": res,
                    "closed_at": datetime.now(timezone.utc).isoformat()})
        save_declared()

        member = interaction.user
        outcome = "TP" if res > 0.05 else ("SL" if res < -0.05 else "BE")
        thread = interaction.channel
        try:
            await thread.edit(
                name=f"{rec['instrument']} {outcome} {res:+.2f}R · {member.display_name}"[:100],
                applied_tags=tag_objects(thread.parent,
                                         declare_tags(interaction.guild, member,
                                                      rec["instrument"], outcome)))
            msg = await thread.fetch_message(rec["message_id"])
            await msg.edit(embed=declared_embed(rec, member), view=None)
        except Exception as e:
            print(f"[declare] не смог обновить тред: {e}")

        held_min = 0
        try:
            held_min = (datetime.now(timezone.utc)
                        - datetime.fromisoformat(rec["opened_at"])).total_seconds() / 60
        except Exception:
            pass
        parts = [f"Закрыто: **{res:+.2f}R**."]

        if held_min < DECLARE_MIN_HOLD_MIN:
            # мгновенное закрытие - не сделка, а станок для очков
            rec["quick"] = True          # и в экзамен такое не считается
            parts.append(f"Заявка прожила меньше {DECLARE_MIN_HOLD_MIN} минут - "
                         f"награда за закрытие не начисляется.")
            db = rec.get("dbet")
            if db and not db.get("resolved"):
                db["resolved"] = True
                credit(member.id, db["amt"])
                parts.append("Ставка на дисциплину возвращена без бонуса.")
                save_declared()
        else:
            add_points(member, R_DECLARED_CLOSED)
            parts.append(f"Начислено {R_DECLARED_CLOSED} {E_R}.")
            db = rec.get("dbet")
            if db and not db.get("resolved"):
                db["resolved"] = True
                kept = res >= -(1 + DISCIPLINE_TOL)
                if kept:
                    bonus = int(db["amt"] * DBET_BONUS + 0.999)
                    credit(member.id, db["amt"] + bonus)
                    db["won"] = True
                    parts.append(f"🤝 Дисциплина выдержана: ставка {db['amt']} R "
                                 f"вернулась с бонусом +{bonus}.")
                else:
                    db["won"] = False
                    parts.append(f"Убыток глубже заявленного стопа - ставка на "
                                 f"дисциплину ({db['amt']} R) сгорела.")
                save_declared()
        grats = exam_check_and_certify(member)
        if grats:
            parts.append(grats)
            lbch = bot.get_channel(LEADERBOARD_CHANNEL_ID)
            if lbch:
                try:
                    await lbch.send(embed=discord.Embed(
                        title="🏛 Экзамен сдан",
                        description=f"{member.mention} закрыл {EXAM_TRADES} заявок подряд "
                                    f"по правилам. CERTIFIED - на карте навсегда.",
                        color=0xd7ecff))
                except Exception as e:
                    print(f"[exam] анонс не ушёл: {e}")
        await interaction.followup.send("\n".join(parts), ephemeral=True)


class DeclaredView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть сделку", style=discord.ButtonStyle.secondary,
                       custom_id="declare_close", emoji="🏁")
    async def close(self, button, interaction):
        tid = str(interaction.channel.id)
        rec = declared.get(tid)
        if rec is None:
            await interaction.response.send_message("Заявка не найдена.", ephemeral=True)
            return
        if rec["uid"] != interaction.user.id:
            await interaction.response.send_message(
                "Закрыть заявку может только тот, кто её открыл.", ephemeral=True)
            return
        if rec.get("status") == "closed":
            await interaction.response.send_message("Она уже закрыта.", ephemeral=True)
            return
        await interaction.response.send_modal(CloseModal(tid))


@bot.slash_command(name="trade", description="Заявить сделку до того, как известен исход")
async def trade(ctx):
    await ctx.send_modal(DeclareModal())


# ==================================================================
#            ОБЩИЙ СЧЁТ СЕРВЕРА И КАРТОЧКА ТРЕЙДЕРА
# ==================================================================
# Обе вещи считаются из одних и тех же заявок и потому живут вместе. Считаем
# ТОЛЬКО заявленные сделки: обычные посты в форуме сюда не идут, потому что там
# решение выкладывать принималось уже после исхода, а это и есть источник
# завышения, ради которого заявка и придумана.
CARD_MIN_TRADES = 5        # ниже этого личные цифры не показываем


def open_declarations(uid=None):
    """Открытые заявки, отдельно свежие и брошенные.

    Брошенные нельзя показывать как «сейчас в рынке»: заявка, забытая месяц
    назад, к рынку отношения не имеет, а на табло выглядела бы живой позицией.
    """
    stale_at = datetime.now(timezone.utc) - timedelta(days=DECLARE_STALE_DAYS)
    live, stale = [], []
    for rec in declared.values():
        if rec.get("status") == "closed":
            continue
        if uid is not None and rec.get("uid") != uid:
            continue
        try:
            (live if datetime.fromisoformat(rec["opened_at"]) >= stale_at else stale).append(rec)
        except Exception:
            stale.append(rec)
    return live, stale


def declared_records(uid=None, since=None, closed_only=True):
    out = []
    for rec in declared.values():
        if uid is not None and rec.get("uid") != uid:
            continue
        if closed_only and rec.get("status") != "closed":
            continue
        if since is not None:
            try:
                if datetime.fromisoformat(rec["opened_at"]) < since:
                    continue
            except Exception:
                continue
        out.append(rec)
    out.sort(key=lambda r: r.get("closed_at") or r.get("opened_at") or "")
    return out


def pnl_summary(records):
    """Свод по списку закрытых заявок."""
    if not records:
        return None
    rs = [r["result_r"] for r in records]
    wins = [x for x in rs if x > 0.05]
    losses = [x for x in rs if x < -0.05]
    be = [x for x in rs if -0.05 <= x <= 0.05]
    decided = len(wins) + len(losses)
    # просадка по кривой: худшее падение от достигнутого максимума
    peak = run = worst = 0.0
    for x in rs:
        run += x
        peak = max(peak, run)
        worst = min(worst, run - peak)
    streak = best_streak = 0
    for x in rs:
        streak = streak + 1 if x > 0.05 else 0
        best_streak = max(best_streak, streak)
    return {
        "n": len(rs), "total": sum(rs), "avg": sum(rs) / len(rs),
        "win": len(wins), "loss": len(losses), "be": len(be),
        "winrate": (len(wins) / decided * 100) if decided else None,
        "best": max(rs), "worst": min(rs), "drawdown": worst,
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "best_streak": best_streak,
    }


def discipline(uid):
    """Доля заявок, доведённых до закрытия, и сколько висит открытыми."""
    mine = [r for r in declared.values() if r.get("uid") == uid]
    if not mine:
        return None, 0, 0
    closed = [r for r in mine if r.get("status") == "closed"]
    live, stale = open_declarations(uid)
    return len(closed) / len(mine) * 100, len(live), len(stale)


def pnl_embed(records, title, note):
    s = pnl_summary(records)
    if s is None:
        return discord.Embed(
            title=title,
            description=("Пока ни одной закрытой заявки.\n\n"
                         "Заявка описывает сделку **до** того, как известен исход - "
                         "команда `/trade`. Именно поэтому такому счёту можно верить."),
            color=0xd7ecff)
    sign = "+" if s["total"] >= 0 else ""
    wr = f"{s['winrate']:.0f}%" if s["winrate"] is not None else "-"
    lines = [
        f"**{sign}{s['total']:.2f}R** за {s['n']} "
        f"{plural(s['n'], 'сделку', 'сделки', 'сделок')}",
        f"винрейт {wr} · средняя {s['avg']:+.2f}R",
        "",
        f"плюсы {s['win']} · минусы {s['loss']}" + (f" · безубыток {s['be']}" if s["be"] else ""),
    ]
    if s["avg_win"] is not None and s["avg_loss"] is not None:
        lines.append(f"средний плюс {s['avg_win']:+.2f}R · средний минус {s['avg_loss']:+.2f}R")
    lines.append(f"лучшая {s['best']:+.2f}R · худшая {s['worst']:+.2f}R")
    lines.append(f"максимальная просадка {s['drawdown']:.2f}R")
    if s["best_streak"] > 1:
        lines.append(f"лучшая серия плюсов: {s['best_streak']}")
    embed = discord.Embed(title=title, description="\n".join(lines), color=0xd7ecff)
    embed.set_footer(text=note)
    return embed


@bot.slash_command(name="pnl", description="Общий счёт сервера по заявленным сделкам")
async def pnl(ctx, период: discord.Option(str, choices=["всё время", "этот месяц"]) = "всё время"):
    since = None
    note = "Считаются только заявленные сделки - те, что описаны до исхода"
    if период == "этот месяц":
        now = datetime.now(PRAGUE)
        since = now.replace(day=1, hour=0, minute=0, second=0,
                            microsecond=0).astimezone(timezone.utc)
        note = f"За {now:%m.%Y}. " + note
    recs = declared_records(since=since)
    live, stale = open_declarations()
    embed = pnl_embed(recs, f"{E_LOGO} Счёт сервера", note)
    if live or stale:
        val = []
        if live:
            val.append(f"{len(live)} {plural(len(live), 'заявка', 'заявки', 'заявок')} "
                       f"ещё не закрыта")
        if stale:
            val.append(f"брошено без закрытия: {len(stale)}")
        embed.add_field(name="Сейчас в рынке", value="\n".join(val), inline=False)
    await ctx.respond(embed=embed)


def card_embed(member):
    """Карточка трейдера плитками, как в панели статистики.

    Одна функция на команду /card и кнопку в my-stats, чтобы у карточки не
    завелось двух расходящихся версий. None, если сделок меньше порога.
    """
    recs = declared_records(uid=member.id)
    if len(recs) < CARD_MIN_TRADES:
        return None, len(recs)
    s = pnl_summary(recs)
    disc, open_n, stale = discipline(member.id)
    sign = "+" if s["total"] >= 0 else ""
    wr = f"{s['winrate']:.0f}%" if s["winrate"] is not None else "-"
    embed = discord.Embed(title="Карточка трейдера", color=0xd7ecff)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.add_field(name="Результат",
                    value=f"**{sign}{s['total']:.2f}R**\n"
                          f"{s['n']} {plural(s['n'], 'сделка', 'сделки', 'сделок')}",
                    inline=True)
    embed.add_field(name="Винрейт",
                    value=f"**{wr}**\n{s['win']}W · {s['loss']}L"
                          + (f" · {s['be']}BE" if s["be"] else ""),
                    inline=True)
    embed.add_field(name="Средняя", value=f"**{s['avg']:+.2f}R**", inline=True)
    embed.add_field(name="Просадка", value=f"**{s['drawdown']:.2f}R**", inline=True)
    embed.add_field(name="Лучшая · худшая",
                    value=f"**{s['best']:+.1f}R** · **{s['worst']:+.1f}R**", inline=True)
    embed.add_field(name="Серия плюсов", value=f"**{s['best_streak']}**", inline=True)
    if disc is not None:
        val = f"**{disc:.0f}%** заявок доведено до закрытия"
        if open_n:
            val += f" · в рынке {open_n}"
        if stale:
            val += f" · брошено {stale}"
        embed.add_field(name="Дисциплина", value=val, inline=False)
    first = recs[0].get("opened_at", "")[:10]
    embed.set_footer(text=f"С {first} · только заявленные сделки (/trade), описанные до исхода")
    return embed, len(recs)


@bot.slash_command(name="card", description="Карта трейдера картинкой")
async def card(ctx, участник: discord.Option(discord.Member, required=False) = None):
    target = участник or ctx.author
    await ctx.defer()
    try:
        img = await build_trader_card(target)
        await ctx.respond(file=discord.File(img, f"card_{target.id}.png"))
        return
    except Exception as e:
        print(f"[card] рендер не удался: {e}")
    embed, n = card_embed(target)
    if embed is None:
        await ctx.respond(f"У {target.display_name} закрытых заявок: {n}.", ephemeral=True)
    else:
        await ctx.respond(embed=embed)


# ==================================================================
#                  УТРЕННИЙ ПРЕМАРКЕТ
# ==================================================================
# Канал стоял с 13 июля. Умер он не от нехватки формы: писать план текстом никто
# не перестал бы из-за отсутствия команды. Умер он потому, что туда стало незачем
# заходить - пустой форум не приглашает.
#
# Поэтому бот сам открывает тред дня и задаёт вопрос. Отвечать можно строкой,
# оформлять пост не нужно. Вечером тот же тред спрашивает, что из этого вышло -
# так план и разбор оказываются в одном месте.
PREMARKET_FORUM_ID = PREMARKETS_CHANNEL_ID
PREMARKET_OPEN_HOUR = 9        # по европейскому времени, до открытия Нью-Йорка
PREMARKET_CLOSE_HOUR = 22      # вечерний вопрос в том же треде

PREMARKET_PROMPTS = [
    "Что смотришь сегодня? Инструмент, уровень, чего ждёшь - хватит одной строки.",
    "Какой уровень сегодня главный и почему именно он?",
    "Где сегодня ждёшь реакцию, и что подтвердит идею, а что её отменит?",
    "С каким сценарием заходишь в день? И при чём поймёшь, что ошибся?",
]


def premarket_state():
    return once_marks.setdefault("premarket", {})


async def open_premarket(guild):
    forum = guild.get_channel(PREMARKET_FORUM_ID)
    if forum is None:
        return None
    now = datetime.now(PRAGUE)
    prompt = PREMARKET_PROMPTS[now.toordinal() % len(PREMARKET_PROMPTS)]

    events = [e for e in usd_events() if e["dt"].date() == now.date() and e["dt"] > now]
    events.sort(key=lambda e: e["dt"])
    lines = [prompt, ""]
    if events:
        lines.append("**Сегодня выходит:**")
        for e in events[:4]:
            lines.append(f"· {e['dt_ny']:%H:%M} NY · {e['dt']:%H:%M} EU "
                         f"{impact_emoji(e['impact'])} {e['title']}")
    else:
        lines.append("Важных выходов по США сегодня нет.")
    lines.append("")
    lines.append("Сделку по плану можно заявить командой /trade - она попадёт в общий счёт.")
    lines.append("Вечером вернусь в этот тред и спрошу, что из этого получилось.")

    embed = discord.Embed(title=f"{E_EAGLE} План на {now:%d.%m}",
                          description="\n".join(lines), color=0xd7ecff)
    embed.set_footer(text="Пиши коротко. Разбор важнее оформления")
    try:
        thread = await forum.create_thread(name=f"План на {now:%d.%m.%Y}", embed=embed)
    except Exception as e:
        print(f"[premarket] не смог открыть тред: {e}")
        return None
    print(f"[premarket] открыт тред {thread.id}")
    return thread.id


async def close_premarket(guild, thread_id):
    thread = guild.get_channel_or_thread(thread_id)
    if thread is None:
        try:
            thread = await bot.fetch_channel(thread_id)
        except Exception:
            return
    # кто сегодня отписался в треде - у них и спрашиваем
    authors = []
    try:
        if getattr(thread, "archived", False):
            await thread.edit(archived=False)
        async for m in thread.history(limit=50):
            if not m.author.bot and m.author.id not in authors:
                authors.append(m.author.id)
    except Exception as e:
        print(f"[premarket] не смог прочитать тред: {e}")
        return
    if not authors:
        return          # никто не писал - вечером дёргать некого
    mentions = " ".join(f"<@{u}>" for u in authors[:10])
    embed = discord.Embed(
        description=(f"{mentions}\n\nДень закрылся. Что из утреннего плана сработало, "
                     f"а что нет? Разбор своей ошибки полезнее ещё одного плюса."),
        color=0xd7ecff)
    try:
        await thread.send(embed=embed,
                          allowed_mentions=discord.AllowedMentions(users=True))
        print(f"[premarket] вечерний вопрос отправлен в {thread_id}")
    except Exception as e:
        print(f"[premarket] вечерний вопрос не ушёл: {e}")


@tasks.loop(minutes=10)
@loop_guard("premarket")
async def premarket_loop():
    now = datetime.now(PRAGUE)
    if now.weekday() >= 5:
        return                       # в выходные плана нет
    st = premarket_state()
    day = now.date().isoformat()

    if now.hour >= PREMARKET_OPEN_HOUR and st.get("opened_day") != day:
        if not feed_cache:
            return                   # без календаря план выйдет неполным
        for guild in bot.guilds:
            tid = await open_premarket(guild)
            if tid:
                st["opened_day"] = day
                st["thread_id"] = tid
                st["closed_day"] = None
                save_runtime_state()
            break

    if (now.hour >= PREMARKET_CLOSE_HOUR and st.get("opened_day") == day
            and st.get("closed_day") != day and st.get("thread_id")):
        st["closed_day"] = day
        save_runtime_state()
        for guild in bot.guilds:
            await close_premarket(guild, st["thread_id"])
            break


# ==================================================================
#              КАРТА ТРЕЙДЕРА (картинкой)
# ==================================================================
# Коллекционная карта в духе TCG. Аниме-арт сюда не идёт сознательно: генерации
# картинок у бота нет, а чужой арт из поисковиков - вопрос авторских прав, что
# для сервера с планами на монетизацию недопустимо. Вместо этого арт - СВОЯ
# кривая доходности по заявленным сделкам, а без сделок - свечной паттерн,
# сгенерированный из user id: у каждого свой и ни у кого не повторяется.
# Титул и подпись выбираются из реальной статистики.
R_TRADE_OF_WEEK = 15
DECLARE_NAG_DAYS = 3
# --- ставка на дисциплину ---
# Ставишь R на то, что доведёшь СВОЮ заявку до конца по правилам. «По правилам»
# проверяется арифметикой, а не голосованием: убыток не глубже заявленного стопа
# (с допуском на проскальзывание) и заявка закрыта, а не брошена. Выдержал -
# ставка возвращается с бонусом, слился или бросил - сгорает.
DBET_MIN, DBET_MAX = 5, 25
DBET_BONUS = 0.5                # доля бонуса от ставки
DISCIPLINE_TOL = 0.1            # насколько глубже -1R прощаем (проскальзывание)
DECLARE_MIN_HOLD_MIN = 15       # раньше - ни награды за закрытие, ни бонуса:
                                # иначе /trade+закрыть за минуту это станок для R

CARD_INK = (17, 24, 32)
CARD_INK2 = (62, 74, 87)
CARD_MUTED = (105, 120, 135)
CARD_ACCENT = (26, 95, 180)
CARD_GREEN = (63, 169, 124)
CARD_RED = (217, 106, 91)


ART_DIR = Path(__file__).parent / "art_cache"

# Заготовки арта по титулам: тёмное, атмосферное, глубокое - вайб сервера.
# Источник wallhaven (SFW-фильтр), выбор детерминирован по uid, результат
# кэшируется на диск, так что сеть нужна один раз на человека.
EPITHET_ART = {
    "Iron Hands": ["samurai armor", "knight dark"],
    "The Sniper": ["hawk", "wolf dark"],
    "The Phoenix": ["phoenix"],
    "Silent Accumulator": ["rain window", "candle dark"],
    "The Legend": ["lion dark", "eagle dark art"],
    "Champion Blood": ["eagle dark art", "throne dark"],
    "Open Book": ["lighthouse storm", "candle dark"],
    "Hot Hand": ["lightning storm"],
    "Timeframe Weaver": ["nebula"],
    "Tape Reader": ["cyberpunk rain", "city night rain"],
    "Theta Gambler": ["hourglass", "chess dark"],
    "Naked Chartist": ["mountain fog", "monochrome"],
    "Value Hunter": ["deep sea", "whale"],
    "The Patient": ["zen", "torii"],
    "Opening Bell": ["city sunrise", "sunrise skyline"],
    "Ritual Keeper": ["torii", "temple night"],
    "Voice of the Floor": ["wolf howl", "wolf moon"],
    "The Grinder": ["forge", "berserk"],
    "First Blood": ["red moon", "blood moon"],
    "Big Spender": ["gold dark"],
    "Point Runner": ["comet", "meteor"],
    "Dark Horse": ["black horse", "horse fog", "horse black white"],
}
# Общий пул - вайб доски владельца: ч/б лошади, самураи, статуи, катаны,
# тёмное аниме. Запросы короткие: длинные хвосты на wallhaven дают пустоту.
GENERIC_ART = ["monochrome", "samurai silhouette", "horse black white",
               "angel statue", "katana dark", "greek statue", "orca",
               "berserk", "sword dark", "cat dark"]

CONCEPT_EPITHETS = {
    "MLTF": ("Timeframe Weaver",
             ["Видит один рынок в четырёх зеркалах сразу.",
              "Старший фрейм решает - он лишь исполняет."]),
    "OrderFlow": ("Tape Reader",
                  ["Читает ленту как открытую переписку маркетмейкера.",
                   "Видит, где лежит стакан, до того как он падает."]),
    "0DTE": ("Theta Gambler",
             ["Живёт один день. Каждый день.",
              "Время - его контрагент, и он его продаёт."]),
    "Price Action": ("Naked Chartist",
                     ["Голый график. Никаких оправданий.",
                      "Индикаторов ноль, убеждённости на сто."]),
    "Market Profile": ("Value Hunter",
                       ["Знает, где рынок спал и где проснётся.",
                        "Торгует не цену - согласие рынка о цене."]),
    "Swing": ("The Patient",
              ["Держит дольше, чем чат помнит тикер.",
               "Его стоп видел три отката и не дрогнул."]),
}


def pick_epithet(uid, earned, s, disc, sess, voice_h,
                 concepts=(), role_names=(), spent=0):
    """Титул по профилю. Заслуга в сделках старше любой активности."""
    streak = sess.get("streak", 0)
    opens_total = sess.get("total", 0)
    n = s["n"] if s else 0
    wr = s["winrate"] if s else None
    total_r = s["total"] if s else 0
    dd = s["drawdown"] if s else 0
    hot = s["best_streak"] if s else 0

    def pools():
        if s and n >= 5 and disc is not None and disc >= 90:
            return "Iron Hands", ["Заявил - закрыл. Без исключений.",
                                  "Дисциплина - тоже позиция."]
        if s and n >= 5 and wr is not None and wr >= 60:
            return "The Sniper", ["Редко стреляет. Часто попадает.",
                                  "Ждёт свой сетап дольше, чем ты держишь убыток."]
        if s and n >= 5 and dd <= -4 and total_r > 0:
            return "The Phoenix", [f"Пережил {dd:.0f}R просадки и вышел в плюс.",
                                   "Горел. Отстроился. Торгует дальше."]
        if s and total_r >= 10:
            return "Silent Accumulator", ["Тихо складывает R, пока чат спорит.",
                                          "Кривая говорит за него."]
        if "Legend" in role_names:
            return "The Legend", ["Роль не выдают. Её признают.",
                                  "Был здесь до того, как это стало сервером."]
        if any(CHAMPION_MARK and CHAMPION_MARK in rn for rn in role_names):
            return "Champion Blood", ["Его концепт взял сезон. Он - часть причины.",
                                      "Носит знак чемпиона, пока не отберут."]
        if s and n >= 5 and total_r < 0:
            return "Open Book", ["Заявляет и минусы. Таких - меньшинство.",
                                 "Честная кривая дороже красивой."]
        if s and hot >= 4:
            return "Hot Hand", [f"{hot} плюса подряд - и рука не остыла.",
                                "Серия, о которой шепчутся в войсе."]
        if n >= 3:
            for label in CONCEPT_EPITHETS:
                if label in concepts:
                    return CONCEPT_EPITHETS[label]
        if streak >= 5:
            return "Opening Bell", ["На открытии раньше самого рынка.",
                                    f"{streak} открытий подряд - и не сбавляет."]
        if opens_total >= 20:
            return "Ritual Keeper", ["Открытие без него - не открытие.",
                                     f"{opens_total} сессий отстоял у колокола."]
        if voice_h >= 30:
            return "Voice of the Floor", ["Голос, который слышал каждый войс.",
                                          f"{int(voice_h)} часов в зале - уже прописка."]
        if n >= 5:
            return "The Grinder", ["Сделка за сделкой. Без драмы.",
                                   "Объём - его аргумент."]
        if n >= 1:
            return "First Blood", ["Первая заявка сделана. Дальше - серия.",
                                   "Уже в игре, счёт открыт."]
        if spent >= 50:
            return "Big Spender", ["R у него не задерживаются - и это стиль.",
                                   "Полмагазина уже его."]
        if earned >= 50:
            return "Point Runner", ["R липнут к нему сами.",
                                    "Зарабатывает быстрее, чем тратит."]
        return "Dark Horse", ["Ещё не показал руку.",
                              "Рано списывать со счетов.",
                              "Карта ждёт своих цифр."]

    name, flavors = pools()
    return name, flavors[uid % len(flavors)]


async def fetch_card_art(uid, epithet):
    """Атмосферная картинка под титул. Кэш на диске, выбор стабилен по uid."""
    ART_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", epithet.lower())
    cached = ART_DIR / f"{uid}_{slug}.jpg"
    if cached.exists():
        return cached.read_bytes()
    rnd = random.Random(uid)
    queries = list(EPITHET_ART.get(epithet, []))
    rnd.shuffle(queries)
    gen = list(GENERIC_ART)
    rnd.shuffle(gen)
    queries += gen
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as h:
            items = []
            # одна пустая выдача не повод сдаваться: пробуем следующие запросы,
            # после третьей попытки снимаем фильтр разрешения
            for attempt, q in enumerate(queries[:6]):
                extra = "&atleast=1600x900" if attempt < 3 else ""
                url = ("https://wallhaven.cc/api/v1/search?q=" + q.replace(" ", "+")
                       + "&categories=110&purity=100&sorting=favorites" + extra)
                async with h.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json(content_type=None)
                items = data.get("data") or []
                if items:
                    break
            if not items:
                print(f"[card-art] пусто по всем запросам ({epithet})")
                return None
            pick = items[rnd.randrange(min(len(items), 16))]["path"]
            async with h.get(pick, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status != 200:
                    return None
                raw = await r.read()
    except Exception as e:
        print(f"[card-art] не достал арт: {e}")
        return None

    def _shrink(b):
        import io as _io
        from PIL import Image, ImageOps
        from PIL import ImageEnhance
        im = Image.open(_io.BytesIO(b)).convert("RGB")
        im = ImageOps.fit(im, (852, 520))
        # приглушаем цвет: карты выглядят одной коллекцией, а не случайными обоями
        im = ImageEnhance.Color(im).enhance(0.45)
        im = ImageEnhance.Contrast(im).enhance(1.07)
        im = ImageEnhance.Brightness(im).enhance(0.96)
        out = _io.BytesIO()
        im.save(out, "JPEG", quality=88)
        return out.getvalue()
    try:
        small = await asyncio.to_thread(_shrink, raw)
        cached.write_bytes(small)
        return small
    except Exception as e:
        print(f"[card-art] не смог обработать: {e}")
        return None


def _card_fonts():
    import matplotlib
    fdir = Path(matplotlib.get_data_path()) / "fonts/ttf"
    from PIL import ImageFont
    def F(fn, size):
        return ImageFont.truetype(str(fdir / fn), size)
    return {
        "name": F("DejaVuSerif-Italic.ttf", 52),
        "name_small": F("DejaVuSerif-Italic.ttf", 40),
        "big": F("DejaVuSerif-Italic.ttf", 64),
        "label": F("DejaVuSans.ttf", 26),
        "epithet": F("DejaVuSerif-Italic.ttf", 54),
        "rank": F("DejaVuSerif-Italic.ttf", 46),
        "flavor": F("DejaVuSans.ttf", 33),
        "stats": F("DejaVuSans.ttf", 27),
        "footer": F("DejaVuSans.ttf", 24),
        "footer_b": F("DejaVuSans-Bold.ttf", 24),
        "curve": F("DejaVuSans-Bold.ttf", 30),
    }


def _vgrad(size, top, bottom):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    w, h = size
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def _wrap(draw, text, font, maxw, maxlines=2):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines[:maxlines]


def _draw_fallback_art(art, ad, aw, ah, pad, curve, uid, F):
    """Арт без картинки из сети: кривая на градиенте либо свечи из uid."""
    import random as _random
    from PIL import Image, ImageDraw
    if curve and len(curve) >= 2:
        pts = [0.0] + list(curve)
        lo, hi = min(min(pts), 0), max(max(pts), 0)
        span = (hi - lo) or 1.0
        def P(i, v):
            return (pad + (aw - 2 * pad) * i / (len(pts) - 1),
                    ah - pad - (ah - 2 * pad) * (v - lo) / span)
        xy = [P(i, v) for i, v in enumerate(pts)]
        zy = P(0, 0)[1]
        ad.line([(pad, zy), (aw - pad, zy)], fill=(150, 170, 195, 120), width=2)
        fill_layer = Image.new("RGBA", art.size, (0, 0, 0, 0))
        ImageDraw.Draw(fill_layer).polygon(
            xy + [(xy[-1][0], zy), (xy[0][0], zy)], fill=CARD_ACCENT + (36,))
        art.alpha_composite(fill_layer)
        ad.line(xy, fill=CARD_ACCENT + (255,), width=6, joint="curve")
        ex, ey = xy[-1]
        ad.ellipse((ex - 9, ey - 9, ex + 9, ey + 9), fill=CARD_ACCENT + (255,))
        ad.text((min(ex, aw - pad - 10), ey - 22), f"{curve[-1]:+.1f}R",
                font=F["curve"], fill=CARD_INK + (255,), anchor="ms")
        return
    rnd = _random.Random(uid)
    n, price, series = 22, 50.0, []
    for _ in range(n):
        o = price
        c = o + rnd.uniform(-7, 8.2)
        hgh = max(o, c) + rnd.uniform(0.5, 4)
        lw = min(o, c) - rnd.uniform(0.5, 4)
        series.append((o, hgh, lw, c)); price = c
    lo = min(x[2] for x in series); hi = max(x[1] for x in series)
    span = (hi - lo) or 1.0
    cw = (aw - 2 * pad) / n
    def Y(v): return ah - pad - (ah - 2 * pad) * (v - lo) / span
    for i, (o, hgh, lw, c) in enumerate(series):
        cx = pad + cw * i + cw / 2
        col = (CARD_GREEN if c >= o else CARD_RED) + (255,)
        ad.line([(cx, Y(hgh)), (cx, Y(lw))], fill=col, width=3)
        top_, bot_ = Y(max(o, c)), Y(min(o, c))
        if bot_ - top_ < 3: bot_ = top_ + 3
        ad.rounded_rectangle((cx - cw * 0.32, top_, cx + cw * 0.32, bot_), 4, fill=col)


def render_trader_card(name, avatar_bytes, earned, rank, epithet, flavor,
                       curve, stats_line, concepts, season, uid, art_bytes=None,
                       certified=None):
    import io as _io
    import random as _random
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    W, H = 960, 1340
    F = _card_fonts()
    bg = _vgrad((W, H), (205, 228, 252), (238, 246, 255)).convert("RGBA")

    # тень и белая карта (верхний отступ больше - там живёт лого сервера)
    M, TOP, R = 64, 126, 44
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (M + 8, TOP + 16, W - M + 8, H - M + 16), R, fill=(20, 40, 70, 70))
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
    card = ImageDraw.Draw(bg)
    card.rounded_rectangle((M, TOP, W - M, H - M), R, fill=(252, 253, 255, 255))
    d = card
    GOLD = (176, 141, 33)
    if certified:
        # сданный экзамен - золотой кант, навсегда
        d.rounded_rectangle((M + 5, TOP + 5, W - M - 5, H - M - 5), R - 5,
                            outline=GOLD + (255,), width=5)

    # фирменный знак в правом верхнем углу фона, как на референсе
    try:
        logo = Image.open(ART_DIR / "logo.png").convert("RGBA").resize((92, 92))
        bg.alpha_composite(logo, (W - M - 92, 16))
    except Exception:
        pass

    # ---------- шапка ----------
    ax, ay, asz = M + 44, TOP + 34, 92
    if avatar_bytes:
        try:
            av = Image.open(_io.BytesIO(avatar_bytes)).convert("RGB")
            av = ImageOps.fit(av, (asz, asz))
            mask = Image.new("L", (asz, asz), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, asz, asz), fill=255)
            bg.paste(av, (ax, ay), mask)
        except Exception:
            avatar_bytes = None
    if not avatar_bytes:
        d.ellipse((ax, ay, ax + asz, ay + asz), fill=(215, 236, 255, 255))
    nf = F["name"] if len(name) <= 13 else F["name_small"]
    d.text((ax + asz + 26, ay + asz // 2), name[:20], font=nf,
           fill=CARD_INK, anchor="lm")
    # справа: заработанные R
    d.text((W - M - 44, ay + 18), "R", font=F["label"], fill=CARD_MUTED, anchor="ra")
    d.text((W - M - 44, ay + 40), f"{earned}", font=F["big"],
           fill=CARD_ACCENT, anchor="ra")

    # ---------- окно арта ----------
    x0, y0, x1, y1 = M + 44, 340, W - M - 44, 850
    amask = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(amask).rounded_rectangle((0, 0, x1 - x0, y1 - y0), 26, fill=255)

    if art_bytes:
        import io as _io2
        try:
            art = ImageOps.fit(Image.open(_io2.BytesIO(art_bytes)).convert("RGB"),
                               (x1 - x0, y1 - y0)).convert("RGBA")
        except Exception:
            art_bytes = None
    if art_bytes:
        ad = ImageDraw.Draw(art)
        aw, ah = art.size
        # лёгкое затемнение к низу, чтобы кривая и подпись читались
        fade = Image.new("RGBA", art.size, (0, 0, 0, 0))
        ImageDraw.Draw(fade).rectangle((0, int(ah * 0.55), aw, ah), fill=(10, 16, 24, 90))
        art.alpha_composite(fade.filter(ImageFilter.GaussianBlur(24)))
        if curve and len(curve) >= 2:
            # кривая доходности светящейся нитью поверх арта, в нижней трети
            pts = [0.0] + list(curve)
            lo, hi = min(min(pts), 0), max(max(pts), 0)
            span = (hi - lo) or 1.0
            gx0, gx1 = 60, aw - 60
            gy1, gy0 = ah - 46, int(ah * 0.60)
            xy = [(gx0 + (gx1 - gx0) * i / (len(pts) - 1),
                   gy1 - (gy1 - gy0) * (v - lo) / span) for i, v in enumerate(pts)]
            glow = Image.new("RGBA", art.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).line(xy, fill=(120, 190, 255, 110), width=11, joint="curve")
            art.alpha_composite(glow.filter(ImageFilter.GaussianBlur(4)))
            ad.line(xy, fill=(255, 255, 255, 235), width=4, joint="curve")
            ex, ey = xy[-1]
            ad.ellipse((ex - 7, ey - 7, ex + 7, ey + 7), fill=(255, 255, 255, 255))
            ad.text((min(ex, aw - 66), ey - 18), f"{curve[-1]:+.1f}R",
                    font=F["curve"], fill=(255, 255, 255, 240), anchor="ms")
        bg.paste(art, (x0, y0), amask)
    else:
        art = _vgrad((x1 - x0, y1 - y0), (219, 233, 252), (241, 233, 247)).convert("RGBA")
        ad = ImageDraw.Draw(art)
        aw, ah = art.size
        pad = 56
        _drew = _draw_fallback_art(art, ad, aw, ah, pad, curve, uid, F)
        bg.paste(art, (x0, y0), amask)


    # ---------- титул ----------
    ty = 922
    # четырёхлучевая звезда
    sx, sy, sr = x0 + 22, ty + 2, 16
    d.polygon([(sx, sy - sr), (sx + sr * .28, sy - sr * .28), (sx + sr, sy),
               (sx + sr * .28, sy + sr * .28), (sx, sy + sr),
               (sx - sr * .28, sy + sr * .28), (sx - sr, sy),
               (sx - sr * .28, sy - sr * .28)], fill=CARD_INK)
    d.text((sx + 40, ty), epithet, font=F["epithet"], fill=CARD_INK, anchor="lm")
    d.text((x1, ty), f"#{rank}", font=F["rank"], fill=CARD_ACCENT, anchor="rm")

    # ---------- подпись ----------
    fy = 992
    for line in _wrap(d, flavor, F["flavor"], x1 - x0 - 20):
        d.text((x0 + 4, fy), line, font=F["flavor"], fill=CARD_INK2)
        fy += 46

    # ---------- строка статистики ----------
    if stats_line:
        d.text((x0 + 4, fy + 26), stats_line, font=F["stats"], fill=CARD_MUTED)
        fy += 40
    if certified:
        d.text((x0 + 4, fy + 26), f"★ CERTIFIED NASDAQISTAN · {certified}",
               font=F["footer_b"], fill=GOLD + (255,))

    # ---------- подвал ----------
    # длинные концепты наезжали на серию - меряем ширины и ужимаемся по шагам
    d.line([(x0, H - M - 96), (x1, H - M - 96)], fill=(226, 233, 242, 255), width=2)
    left = f"NASDAQISTAN · TRADER SERIES · {season}"
    right = (" · ".join(concepts[:2]) if concepts else "LIMITED EDITION").upper()
    def fits():
        return (d.textlength(left, font=F["footer"])
                + d.textlength(right, font=F["footer_b"]) + 34) <= (x1 - x0)
    if not fits():
        left = f"NASDAQISTAN · {season}"
    if not fits() and concepts:
        right = concepts[0].upper()
    while not fits() and len(right) > 5:
        right = right[:-2].rstrip(" ·") + "…"
    d.text((x0, H - M - 62), left, font=F["footer"], fill=CARD_MUTED)
    d.text((x1, H - M - 62), right, font=F["footer_b"], fill=CARD_INK2, anchor="ra")

    out = _io.BytesIO()
    bg.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


async def build_trader_card(member):
    """Собрать данные и отрисовать карту (рендер в отдельном потоке)."""
    rec = points.get(member.id, {})
    earned = rec.get("all", 0)
    earners = [v.get("all", 0) for v in points.values() if v.get("all", 0) > 0]
    rank = (1 + sum(1 for e in earners if e > earned)) if earned > 0 else len(earners) + 1
    recs = declared_records(uid=member.id)
    s = pnl_summary(recs)
    disc, _, _ = discipline(member.id)
    sess = session_state.get(str(member.id), {})
    vh = voice_totals.get(member.id, 0) / 3600
    concepts = [label for label, rid, _ in CONCEPTS.values()
                if any(r.id == rid for r in member.roles)]
    role_names = [r.name for r in member.roles]
    spent = max(rec.get("spent", 0), 0)
    epithet, flavor = pick_epithet(member.id, earned, s, disc, sess, vh,
                                   concepts=concepts, role_names=role_names,
                                   spent=spent)
    curve = None
    if len(recs) >= 2:
        run, curve = 0.0, []
        for r in recs:
            run += r["result_r"]
            curve.append(run)
    stats_line = None
    if s:
        wr = f"{s['winrate']:.0f}%" if s["winrate"] is not None else "-"
        stats_line = (f"{s['n']} {plural(s['n'], 'сделка', 'сделки', 'сделок')} · "
                      f"WR {wr} · сред {s['avg']:+.2f}R")
        if disc is not None:
            stats_line += f" · дисциплина {disc:.0f}%"
    art_bytes = await fetch_card_art(member.id, epithet)
    avatar = None
    try:
        url = str(member.display_avatar.replace(format="png", size=256))
    except Exception:
        url = str(member.display_avatar)
    try:
        async with aiohttp.ClientSession() as http_s:
            async with http_s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    avatar = await r.read()
    except Exception:
        avatar = None
    season = f"S{datetime.now(PRAGUE):%m.%y}"
    cert = exam_state.get(str(member.id), {}).get("certified_at")
    cert_date = None
    if cert:
        cert_date = f"{datetime.fromisoformat(cert).astimezone(PRAGUE):%d.%m.%y}"
    return await asyncio.to_thread(
        render_trader_card, member.display_name, avatar, earned, rank,
        epithet, flavor, curve, stats_line, concepts, season, member.id,
        art_bytes, cert_date)


def best_trade_of_week(now_utc):
    """Лучшая закрытая заявка за 7 дней. None, если закрытых не было."""
    since = now_utc - timedelta(days=7)
    best = None
    for tid, rec in declared.items():
        if rec.get("status") != "closed":
            continue
        try:
            if datetime.fromisoformat(rec["closed_at"]) < since:
                continue
        except Exception:
            continue
        if best is None or rec["result_r"] > best[1]["result_r"]:
            best = (tid, rec)
    return best


@tasks.loop(hours=6)
@loop_guard("declare-nag")
async def declare_nag_loop():
    """Напомнить про висящую заявку: раз на 3-й день, раз при списании в брошенные.

    Качество счёта сервера держится на закрытых заявках - забытая портит и
    карточку автора, и дисциплину. Дважды и хватит: дальше это уже спам.
    """
    now = datetime.now(timezone.utc)
    for tid, rec in list(declared.items()):
        if rec.get("status") == "closed":
            continue
        try:
            age = (now - datetime.fromisoformat(rec["opened_at"])).days
        except Exception:
            continue
        if age >= DECLARE_STALE_DAYS and not rec.get("nagged_stale"):
            stage = "stale"; rec["nagged_stale"] = True
            rec["nagged"] = True    # иначе на следующем проходе прилетит ещё и
                                    # трёхдневное напоминание задним числом
            db = rec.get("dbet")
            if db and not db.get("resolved"):
                db["resolved"] = True
                db["won"] = False   # бросил заявку - ставка сгорает, в этом и суть
        elif age >= DECLARE_NAG_DAYS and not rec.get("nagged"):
            stage = "nag"; rec["nagged"] = True
        else:
            continue
        save_declared()
        thread = bot.get_channel(int(tid))
        if thread is None:
            try:
                thread = await bot.fetch_channel(int(tid))
            except Exception:
                continue
        try:
            if getattr(thread, "archived", False):
                await thread.edit(archived=False)
            if stage == "nag":
                text = (f"<@{rec['uid']}> заявка открыта уже {age} "
                        f"{plural(age, 'день', 'дня', 'дней')}. Ты ещё в позиции? "
                        f"Если вышел - закрой кнопкой, результат попадёт в карту.")
            else:
                text = (f"<@{rec['uid']}> заявка висит {age} "
                        f"{plural(age, 'день', 'дня', 'дней')} и помечена брошенной. "
                        f"Закрыть всё ещё можно - кнопка на месте.")
                if rec.get("dbet", {}).get("won") is False and rec["dbet"].get("resolved"):
                    text += " Ставка на дисциплину сгорела - заявка не доведена."
            await thread.send(text, allowed_mentions=discord.AllowedMentions(users=True))
        except Exception as e:
            print(f"[declare-nag] {tid}: {e}")


# ==================================================================
#                      АУКЦИОН НЕДЕЛИ
# ==================================================================
# Один редкий лот в неделю, закрытые ставки в R. Ставка победителя СГОРАЕТ -
# это главный сток экономики: прайс-лист магазина цены фиксирует, аукцион
# позволяет рынку самому решить, сколько стоит редкое. Ставки не видны никому
# до закрытия - иначе побеждал бы не тот, кто ценит лот, а тот, кто зашёл
# последним и перебил на единицу.
AUCTION_CHANNEL_ID = NEWS_CHANNEL_ID
AUCTION_STATE_FILE = "auction_state.json"
AUCTION_OPEN_DAY, AUCTION_OPEN_HOUR = 0, 12      # Пн 12:00
AUCTION_CLOSE_DAY, AUCTION_CLOSE_HOUR = 4, 20    # Пт 20:00
AUCTION_MIN_BID = 10

AUCTION_LOTS = [
    {"label": "Закреп твоего трейда на неделю",
     "desc": "Твой тред из team-trades висит первым 7 дней. "
             "Слот в форуме ровно один - Discord больше не даёт.",
     "kind": "pin"},
    {"label": "Тема следующего эфира",
     "desc": "Команда разбирает то, что выберешь ты.", "kind": "manual"},
    {"label": "Цвет ника на месяц",
     "desc": "Любой цвет из магазина, 30 дней вместо 14.", "kind": "manual"},
    {"label": "Личный разбор сделки",
     "desc": "Команда разбирает твою сделку по косточкам.", "kind": "manual"},
]

auction = {}   # {"week","lot_idx","msg_id","channel_id","bids":{uid:[amt,ts]},"closed"}


def load_auction():
    global auction
    if os.path.exists(AUCTION_STATE_FILE):
        try:
            with open(AUCTION_STATE_FILE, "r") as f:
                auction = json.load(f)
        except Exception as e:
            print(f"auction load error: {e}")
            auction = {}


def save_auction():
    save_json_atomic(AUCTION_STATE_FILE, auction, "auction")


def auction_winner():
    """(uid, ставка) - максимум, при равенстве побеждает более ранняя."""
    bids = auction.get("bids", {})
    if not bids:
        return None
    uid = min(bids, key=lambda u: (-bids[u][0], bids[u][1]))
    return int(uid), bids[uid][0]


class AuctionBidModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Ставка на лот недели")
        self.add_item(discord.ui.InputText(
            label=f"Сколько R (минимум {AUCTION_MIN_BID})", placeholder="25"))

    async def callback(self, interaction: discord.Interaction):
        if auction.get("closed", True):
            await interaction.response.send_message("Аукцион закрыт.", ephemeral=True)
            return
        try:
            amt = int(str(self.children[0].value).strip())
        except ValueError:
            await interaction.response.send_message("Ставка должна быть целым числом.",
                                                    ephemeral=True)
            return
        if amt < AUCTION_MIN_BID:
            await interaction.response.send_message(
                f"Минимальная ставка {AUCTION_MIN_BID} R.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        old = auction["bids"].get(uid)
        if old and amt <= old[0]:
            await interaction.response.send_message(
                f"Твоя текущая ставка {old[0]} R - новую можно только поднять.",
                ephemeral=True)
            return
        delta = amt - (old[0] if old else 0)
        if balance(interaction.user.id) < delta:
            await interaction.response.send_message(
                f"Не хватает R: доплата {delta}, на балансе {balance(interaction.user.id)}.",
                ephemeral=True)
            return
        spend(interaction.user.id, delta)          # эскроу: возврат проигравшим при закрытии
        auction["bids"][uid] = [amt, datetime.now(timezone.utc).isoformat()]
        save_auction()
        await interaction.response.send_message(
            f"Ставка принята: **{amt} R** (заморожены до закрытия).\n"
            f"Чужих ставок не видно - таков формат. Поднять свою можно той же кнопкой.",
            ephemeral=True)


class AuctionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Сделать ставку", style=discord.ButtonStyle.secondary,
                       custom_id="auction_bid", emoji="🔨")
    async def bid(self, button, interaction):
        if auction.get("closed", True):
            await interaction.response.send_message("Аукцион закрыт.", ephemeral=True)
            return
        await interaction.response.send_modal(AuctionBidModal())

    @discord.ui.button(label="Моя ставка", style=discord.ButtonStyle.secondary,
                       custom_id="auction_my", emoji="👁", row=0)
    async def my(self, button, interaction):
        b = auction.get("bids", {}).get(str(interaction.user.id))
        n = len(auction.get("bids", {}))
        text = (f"Твоя ставка: **{b[0]} R**." if b else "Ты ещё не ставил.")
        await interaction.response.send_message(
            f"{text}\nУчастников в аукционе: {n}.", ephemeral=True)


async def open_auction(channel):
    week = datetime.now(PRAGUE).strftime("%Y-W%W")
    lot = AUCTION_LOTS[int(week[-2:]) % len(AUCTION_LOTS)]
    embed = discord.Embed(
        title=f"🔨 Аукцион недели: {lot['label']}",
        description=(f"{lot['desc']}\n\n"
                     f"Ставки **закрытые** - никто не видит чужих. "
                     f"Минимум {AUCTION_MIN_BID} {E_R}, поднимать свою можно до закрытия.\n"
                     f"Ставка замораживается сразу; проигравшим вернётся всё, "
                     f"ставка победителя **сгорает**.\n\n"
                     f"Закрытие: **пятница 20:00**."),
        color=0xd7ecff)
    embed.set_footer(text="Один лот. Один победитель. Рынок решает цену")
    msg = await channel.send(embed=embed, view=AuctionView())
    auction.clear()
    auction.update({"week": week, "lot_idx": int(week[-2:]) % len(AUCTION_LOTS),
                    "msg_id": msg.id, "channel_id": channel.id,
                    "bids": {}, "closed": False})
    save_auction()
    print(f"[auction] открыт лот «{lot['label']}»")


async def settle_auction(guild):
    auction["closed"] = True
    save_auction()
    lot = AUCTION_LOTS[auction.get("lot_idx", 0)]
    channel = bot.get_channel(auction.get("channel_id") or AUCTION_CHANNEL_ID)
    win = auction_winner()

    # проигравшим - возврат
    for uid, (amt, _ts) in auction.get("bids", {}).items():
        if win and int(uid) == win[0]:
            continue
        credit(int(uid), amt)
    save_auction()

    if win is None:
        if channel:
            await channel.send(embed=discord.Embed(
                title="🔨 Аукцион закрыт", color=0xd7ecff,
                description=f"Лот «{lot['label']}» остался без ставок. Бывает."))
        return

    uid, amt = win
    desc = (f"Лот «**{lot['label']}**» уходит <@{uid}> за **{amt} {E_R}**.\n"
            f"Ставка сгорает - так R покидают оборот. "
            f"Остальным участникам ставки возвращены.")

    if lot["kind"] == "pin":
        member = guild.get_member(uid)
        thread = None
        forum = guild.get_channel(TEAM_TRADES_CHANNEL_ID)
        if member and forum:
            mine = [t for t in forum.threads if t.owner_id == uid]
            thread = max(mine, key=lambda t: t.created_at, default=None)
        if thread is None:
            credit(uid, amt)     # закреплять нечего - деньги назад, лот в ручную выдачу
            desc += ("\n\n⚠️ У победителя нет треда в team-trades - ставка возвращена, "
                     "команда свяжется по замене лота.")
        else:
            try:
                await thread.edit(pinned=True, reason="лот аукциона")
                until = datetime.now(timezone.utc) + timedelta(days=7)
                shop_grants.append({"uid": uid, "kind": "pin_thread",
                                    "thread_id": thread.id, "label": "закреп (аукцион)",
                                    "until": until.isoformat()})
                save_shop_state()
                desc += f"\nЗакреплён «{thread.name[:50]}» до {until.astimezone(PRAGUE):%d.%m %H:%M}."
            except Exception as e:
                print(f"[auction] закреп не удался: {e}")
                credit(uid, amt)
                desc += "\n\n⚠️ Закрепить не вышло - ставка возвращена."
    else:
        adm = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
        if adm:
            try:
                await adm.send(embed=discord.Embed(
                    title="🔨 Выдай лот аукциона", color=0xffaa33,
                    description=f"<@{uid}> выиграл «{lot['label']}» за {amt} R."))
            except Exception:
                pass
        desc += "\nКоманда свяжется с победителем по выдаче."

    if channel:
        try:
            await channel.send(embed=discord.Embed(
                title="🔨 Аукцион закрыт", description=desc, color=0xd7ecff))
        except Exception as e:
            print(f"[auction] итог не ушёл: {e}")


@tasks.loop(minutes=10)
@loop_guard("auction")
async def auction_loop():
    now = datetime.now(PRAGUE)
    week = now.strftime("%Y-W%W")
    channel = bot.get_channel(AUCTION_CHANNEL_ID)
    if channel is None:
        return
    past_open = (now.weekday(), now.hour) >= (AUCTION_OPEN_DAY, AUCTION_OPEN_HOUR)
    past_close = (now.weekday(), now.hour) >= (AUCTION_CLOSE_DAY, AUCTION_CLOSE_HOUR)
    if auction.get("week") != week:
        if past_open and not past_close:      # не открываем задним числом в выходные
            await open_auction(channel)
        return
    if not auction.get("closed") and past_close:
        for guild in bot.guilds:
            await settle_auction(guild)
            break


# ==================================================================
#                      ЭКЗАМЕН СЕРВЕРА
# ==================================================================
# Проп-фирмы продают evaluation за деньги; сервер выдаёт свой бесплатно и
# честнее - сделки заявлены ДО исхода, скриншот тут не поможет. Норматив:
# EXAM_TRADES подряд доведённых по правилам заявок (стоп не глубже заявленного,
# ничего не брошено), просадка внутри этой серии не глубже EXAM_MAX_DD.
# Сдал - CERTIFIED на карте навсегда, даже если потом серия порвётся.
EXAM_FILE = "exam_state.json"
EXAM_TRADES = 10
EXAM_MAX_DD = -5.0

exam_state = {}   # uid(str) -> {"certified_at": iso, "dd": float}


def load_exam():
    global exam_state
    if os.path.exists(EXAM_FILE):
        try:
            with open(EXAM_FILE, "r") as f:
                exam_state = json.load(f)
        except Exception as e:
            print(f"exam load error: {e}")
            exam_state = {}


def save_exam():
    save_json_atomic(EXAM_FILE, exam_state, "exam")


def exam_events(uid):
    """Хронология завершённых событий заявок участника.

    'kept'   - закрыта по правилам (учитывается и в серию, и в просадку)
    'broken' - стоп уехал глубже заявленного ЛИБО заявка брошена в stale.
    Мгновенные закрытия (quick) не считаются вовсе: иначе десять закрытий
    за минуту делали бы сертификат станком.
    """
    stale_at = datetime.now(timezone.utc) - timedelta(days=DECLARE_STALE_DAYS)
    evs = []
    recs = sorted((r for r in declared.values() if r.get("uid") == uid),
                  key=lambda r: r.get("opened_at", ""))
    for r in recs:
        if r.get("status") == "closed":
            if r.get("quick"):
                continue
            kept = r["result_r"] >= -(1 + DISCIPLINE_TOL)
            evs.append(("kept" if kept else "broken", r["result_r"]))
        else:
            try:
                if datetime.fromisoformat(r["opened_at"]) < stale_at:
                    evs.append(("broken", None))
            except Exception:
                pass
    return evs


def exam_progress(uid):
    """(текущая чистая серия, просадка последних до EXAM_TRADES из неё, сдан ли)."""
    evs = exam_events(uid)
    streak_r = []
    for kind, r in reversed(evs):
        if kind == "broken":
            break
        streak_r.append(r)
    streak = len(streak_r)
    tail = list(reversed(streak_r))[-EXAM_TRADES:]
    peak = run = dd = 0.0
    for r in tail:
        run += r
        peak = max(peak, run)
        dd = min(dd, run - peak)
    ok = streak >= EXAM_TRADES and dd >= EXAM_MAX_DD
    return streak, dd, ok


def exam_check_and_certify(member):
    """Вернёт текст поздравления, если участник только что сдал."""
    key = str(member.id)
    if key in exam_state:
        return None
    streak, dd, ok = exam_progress(member.id)
    if not ok:
        return None
    exam_state[key] = {"certified_at": datetime.now(timezone.utc).isoformat(),
                       "dd": round(dd, 2)}
    save_exam()
    return (f"🏛 **ЭКЗАМЕН СДАН.** {EXAM_TRADES} заявок подряд по правилам, "
            f"просадка {dd:.1f}R. Рамка CERTIFIED на карте - теперь навсегда.")


async def get_or_create_exam_message(channel):
    """Зал славы + кто сейчас на нормативе. Пятое закреплённое табло."""
    lines = []
    if exam_state:
        lines.append("**Сдали экзамен:**")
        rows = sorted(exam_state.items(), key=lambda kv: kv[1]["certified_at"])
        for uid, rec in rows:
            d = datetime.fromisoformat(rec["certified_at"]).astimezone(PRAGUE)
            lines.append(f"🏛 <@{uid}> — {d:%d.%m.%Y}")
        lines.append("")
    active = []
    for uid in {r.get("uid") for r in declared.values() if r.get("uid")}:
        if str(uid) in exam_state:
            continue
        streak, dd, _ = exam_progress(uid)
        if streak > 0:
            active.append((streak, dd, uid))
    if active:
        active.sort(reverse=True)
        lines.append("**На нормативе сейчас:**")
        for streak, dd, uid in active[:5]:
            lines.append(f"▫️ <@{uid}> — {min(streak, EXAM_TRADES)}/{EXAM_TRADES}"
                         + (f" · просадка {dd:.1f}R" if dd < 0 else ""))
    if not lines:
        lines = ["Пока никто не вышел на норматив. Всё начинается с /trade."]
    desc = "\n".join(lines) + (
        f"\n\nНорматив: **{EXAM_TRADES} заявок подряд** по правилам "
        f"(стоп не глубже заявленного, ничего не брошено), "
        f"просадка серии не глубже **{EXAM_MAX_DD:.0f}R**. "
        f"Свой прогресс: /exam")
    embed = discord.Embed(title="🏛 ЭКЗАМЕН NASDAQISTAN", description=desc, color=0xd7ecff)
    embed.set_footer(text="Сделки заявлены до исхода - сертификат не подделывается")
    msg_id = lb_state.get("exam_msg", 0)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except Exception:
            pass
    msg = await channel.send(embed=embed,
                             allowed_mentions=discord.AllowedMentions(users=False))
    lb_state["exam_msg"] = msg.id
    save_lb_state()
    try:
        await msg.pin()
        await purge_pin_notice(channel)
    except Exception as e:
        print(f"[exam] не удалось закрепить табло: {e}")


@bot.slash_command(name="exam", description="Твой прогресс по экзамену сервера")
async def exam_cmd(ctx):
    key = str(ctx.author.id)
    if key in exam_state:
        d = datetime.fromisoformat(exam_state[key]["certified_at"]).astimezone(PRAGUE)
        await ctx.respond(f"🏛 Экзамен сдан {d:%d.%m.%Y}. Рамка CERTIFIED на твоей карте.",
                          ephemeral=True)
        return
    streak, dd, ok = exam_progress(ctx.author.id)
    left = max(0, EXAM_TRADES - streak)
    lines = [f"Серия по правилам: **{streak}** из {EXAM_TRADES}"]
    if streak:
        lines.append(f"Просадка серии: **{dd:.1f}R** (лимит {EXAM_MAX_DD:.0f}R)")
    if left:
        lines.append(f"До сертификата: {left} "
                     f"{plural(left, 'заявка', 'заявки', 'заявок')} по правилам.")
    elif dd < EXAM_MAX_DD:
        lines.append("Серия есть, но просадка глубже лимита - "
                     "каждая новая чистая заявка сдвигает окно.")
    lines.append("\nСерию рвёт: стоп глубже заявленного или брошенная заявка. "
                 "Мгновенные закрытия не считаются вовсе.")
    await ctx.respond("\n".join(lines), ephemeral=True)


# ==================================================================
#                       РЕПЛЕЙ-АРЕНА
# ==================================================================
# Пятничное шоу: бот проигрывает скрытый торговый день по 15-минуткам. На
# стоп-точках комната ставит R на направление следующего часа; каждый раунд -
# свой тотализатор. Bar replay соло есть у всех платформ; СОВМЕСТНОГО, как
# события с комнатой в войсе, нет ни у кого - в этом и смысл.
#
# Ответы каждого раунда известны в момент старта (лежат в тех же данных),
# поэтому событие не зависит ни от одного сетевого вызова после начала.
ARENA_CHANNEL_ID = NEWS_CHANNEL_ID
ARENA_STATE_FILE = "arena_state.json"
ARENA_DAY, ARENA_HOUR = 4, 21        # пятница 21:00 по Европе
ARENA_ROUNDS = 6
ARENA_STAKE = 10                     # фиксированная ставка раунда
ARENA_BET_SECONDS = 75
ARENA_CONTEXT = 26                   # свечей контекста перед первой стоп-точкой
ARENA_STEP = 4                       # свечей открывается за раунд (час на 15м)
ARENA_CHAMPION_BONUS = 15

arena = {"active": False, "round": None}   # текущий раунд: {bets:{uid:side}, answer}


def load_arena():
    """После рестарта живой раунд не восстановить - возвращаем ставки."""
    global arena
    if not os.path.exists(ARENA_STATE_FILE):
        return
    try:
        with open(ARENA_STATE_FILE) as f:
            saved = json.load(f)
    except Exception:
        return
    rnd = saved.get("round")
    if rnd and rnd.get("bets"):
        for uid in rnd["bets"]:
            credit(int(uid), ARENA_STAKE)
        print(f"[arena] рестарт посреди раунда: возвращено {len(rnd['bets'])} ставок")
    arena = {"active": False, "round": None}
    save_arena()


def save_arena():
    save_json_atomic(ARENA_STATE_FILE, arena, "arena")


class ArenaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _bet(self, interaction, side):
        rnd = arena.get("round")
        if not arena.get("active") or rnd is None or rnd.get("locked"):
            await interaction.response.send_message("Приём ставок на этот раунд закрыт.",
                                                    ephemeral=True)
            return
        uid = str(interaction.user.id)
        if uid in rnd["bets"]:
            await interaction.response.send_message(
                f"Ты уже поставил на «{'вверх' if rnd['bets'][uid]=='up' else 'вниз'}» "
                f"в этом раунде.", ephemeral=True)
            return
        if not spend(interaction.user.id, ARENA_STAKE):
            await interaction.response.send_message(
                f"Не хватает R: раунд стоит {ARENA_STAKE}, у тебя "
                f"{balance(interaction.user.id)}.", ephemeral=True)
            return
        rnd["bets"][uid] = side
        save_arena()
        await interaction.response.send_message(
            f"Принято: {ARENA_STAKE} R на «{'вверх' if side=='up' else 'вниз'}». "
            f"Ставок в раунде: {len(rnd['bets'])}.", ephemeral=True)

    @discord.ui.button(label=f"▲ вверх", style=discord.ButtonStyle.secondary,
                       custom_id="arena_up", emoji="📈")
    async def up(self, button, interaction):
        await self._bet(interaction, "up")

    @discord.ui.button(label=f"▼ вниз", style=discord.ButtonStyle.secondary,
                       custom_id="arena_down", emoji="📉")
    async def down(self, button, interaction):
        await self._bet(interaction, "down")


async def run_arena(channel):
    """Само событие: контекст -> раунды со стоп-точками -> итоги вечера."""
    ticker = random.choice(list(BLIND_INSTRUMENTS))
    candles = await fetch_candles(ticker, rng="60d", interval="15m")
    need = ARENA_CONTEXT + ARENA_ROUNDS * ARENA_STEP
    if len(candles) < need + 40:
        print("[arena] мало данных")
        return False
    start = random.randint(20, len(candles) - need - 10)
    window = candles[start:start + need]

    totals = {}          # uid -> чистый результат вечера
    arena["active"] = True

    intro = discord.Embed(
        title="🏟 РЕПЛЕЙ-АРЕНА",
        description=(f"Скрытый кусок реальной истории. {ARENA_ROUNDS} раундов: "
                     f"на каждой стоп-точке у тебя **{ARENA_BET_SECONDS} секунд** "
                     f"решить, куда пойдёт следующий час.\n"
                     f"Раунд - {ARENA_STAKE} {E_R}, банк раунда делят угадавшие. "
                     f"Лучший результат вечера получает +{ARENA_CHAMPION_BONUS} {E_R} "
                     f"и звание трейдера арены.\n\nПервый график - через минуту. "
                     f"Инструмент не скажу."),
        color=0xd7ecff)
    await channel.send(embed=intro)
    await asyncio.sleep(60)

    for rd in range(ARENA_ROUNDS):
        visible = window[:ARENA_CONTEXT + rd * ARENA_STEP]
        future = window[ARENA_CONTEXT + rd * ARENA_STEP:
                        ARENA_CONTEXT + (rd + 1) * ARENA_STEP]
        ref = visible[-1][4]
        answer = "up" if future[-1][4] > ref else "down"
        move = (future[-1][4] - ref) / ref * 100

        img = await asyncio.to_thread(render_chart, visible[-60:],
                                      f"Раунд {rd + 1} из {ARENA_ROUNDS}  ·  куда следующий час?")
        arena["round"] = {"bets": {}, "answer": answer, "locked": False}
        save_arena()
        embed = discord.Embed(
            title=f"🏟 Раунд {rd + 1}/{ARENA_ROUNDS}",
            description=f"{ARENA_BET_SECONDS} секунд на решение. "
                        f"Ставка {ARENA_STAKE} {E_R}, одна на раунд.",
            color=0xd7ecff)
        embed.set_image(url="attachment://round.png")
        await channel.send(embed=embed, file=discord.File(img, "round.png"),
                           view=ArenaView())
        await asyncio.sleep(ARENA_BET_SECONDS)

        rnd = arena["round"]
        rnd["locked"] = True
        save_arena()
        players = rnd["bets"]
        where = "вверх" if answer == "up" else "вниз"
        if not players:
            res_text = f"Цена ушла **{where}** на {abs(move):.2f}%. Ставок не было."
        else:
            winners = [u for u, s in players.items() if s == answer]
            pool = ARENA_STAKE * len(players)
            for u in players:
                totals.setdefault(int(u), 0)
                totals[int(u)] -= ARENA_STAKE
            if winners:
                share = pool // len(winners)
                for u in winners:
                    credit(int(u), share)
                    totals[int(u)] += share
                res_text = (f"Цена ушла **{where}** на {abs(move):.2f}%. "
                            f"Банк {pool} {E_R} на {len(winners)} угадавших из {len(players)}.")
            else:
                res_text = (f"Цена ушла **{where}** на {abs(move):.2f}%. "
                            f"Никто не угадал - банк {pool} {E_R} сгорел.")
        reveal = await asyncio.to_thread(
            render_chart, (visible + future)[-60:], f"Раунд {rd + 1}  ·  ответ")
        await channel.send(embed=discord.Embed(description=res_text, color=0xd7ecff)
                           .set_image(url="attachment://reveal.png"),
                           file=discord.File(reveal, "reveal.png"))
        arena["round"] = None
        save_arena()
        if rd < ARENA_ROUNDS - 1:
            await asyncio.sleep(12)

    arena["active"] = False
    save_arena()

    lines = [f"Это был **{BLIND_INSTRUMENTS.get(ticker, ticker)}**."]
    if totals:
        board = sorted(totals.items(), key=lambda kv: -kv[1])
        champ, best = board[0]
        if best > 0:
            credit(champ, ARENA_CHAMPION_BONUS)
            lines.append(f"\n🏆 Трейдер арены: <@{champ}> ({best:+d} {E_R} за вечер, "
                         f"+{ARENA_CHAMPION_BONUS} бонусом).")
        lines.append("")
        for u, v in board[:8]:
            lines.append(f"{'▲' if v > 0 else '▽'} <@{u}> — {v:+d} {E_R}")
    else:
        lines.append("Ставок за вечер не было. Попробуем в следующую пятницу.")
    await channel.send(embed=discord.Embed(title="🏟 Итоги арены",
                                           description="\n".join(lines), color=0xd7ecff),
                       allowed_mentions=discord.AllowedMentions(users=False))
    return True


@tasks.loop(minutes=1)
@loop_guard("arena")
async def arena_loop():
    now = datetime.now(PRAGUE)
    week = now.strftime("%Y-W%W")
    if (now.weekday() != ARENA_DAY or now.hour != ARENA_HOUR
            or once_marks.get("arena_week") == week or arena.get("active")):
        return
    channel = bot.get_channel(ARENA_CHANNEL_ID)
    if channel is None:
        return
    once_marks["arena_week"] = week      # помечаем до старта: событие в процессе
    save_runtime_state()                 # не должно перезапуститься вторым потоком
    try:
        ok = await run_arena(channel)
        if not ok:                       # не собралось - вернём попытку через час
            once_marks.pop("arena_week", None)
            save_runtime_state()
    finally:
        rnd = arena.get("round")
        if rnd and rnd.get("bets"):
            # упали между приёмом ставок и выплатой - деньги возвращаются,
            # ровно как при рестарте: событие не имеет права их съесть
            for uid in rnd["bets"]:
                credit(int(uid), ARENA_STAKE)
            print(f"[arena] аварийное завершение: возвращено {len(rnd['bets'])} ставок")
        arena["active"] = False
        arena["round"] = None
        save_arena()


# ==================================================================
#                       КАРТА ВЫЗОВА
# ==================================================================
# Воскресный рендер «карты фонда»: неделя сервера по заявленным сделкам в том же
# коллекционном стиле. «Мы +74% в месяц» пишут все и не верит никто; карта с
# честными цифрами и проверяемой механикой - открытый вызов. Владелец публикует
# её в TG/X - маркетинг, встроенный в бота.
FUNDCARD_DAY, FUNDCARD_HOUR = 6, 19     # воскресенье 19:00


def render_fund_card(week_no, n, total, wr, disc, curve, season):
    import io as _io
    from PIL import Image, ImageDraw, ImageFilter

    W, H = 1080, 1080                     # квадрат: так живёт в соцсетях
    F = _card_fonts()
    bg = _vgrad((W, H), (16, 24, 36), (28, 40, 58)).convert("RGBA")

    M, R = 64, 40
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((M + 8, M + 14, W - M + 8, H - M + 14),
                                             R, fill=(0, 0, 0, 120))
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle((M, M, W - M, H - M), R, fill=(22, 32, 46, 255))
    d.rounded_rectangle((M + 4, M + 4, W - M - 4, H - M - 4), R - 4,
                        outline=(109, 174, 255, 90), width=2)

    try:
        logo = Image.open(ART_DIR / "logo.png").convert("RGBA").resize((72, 72))
        white = Image.new("RGBA", logo.size, (232, 239, 246, 255))
        white.putalpha(logo.split()[3])
        bg.alpha_composite(white, (M + 44, M + 40))
    except Exception:
        pass
    d.text((M + 132, M + 76), "NASDAQISTAN", font=F["epithet"],
           fill=(232, 239, 246, 255), anchor="lm")
    d.text((W - M - 44, M + 76), f"WEEK {week_no}", font=F["rank"],
           fill=(109, 174, 255, 255), anchor="rm")

    # главная цифра
    sign = "+" if total >= 0 else ""
    col = (76, 191, 139, 255) if total >= 0 else (224, 112, 95, 255)
    d.text((M + 44, 258), f"{sign}{total:.1f}R", font=F["big"], fill=col)
    d.text((M + 46, 348), f"{n} {plural(n, 'заявленная сделка', 'заявленные сделки', 'заявленных сделок')}"
           + (f" · винрейт {wr:.0f}%" if wr is not None else "")
           + (f" · дисциплина {disc:.0f}%" if disc is not None else ""),
           font=F["stats"], fill=(133, 147, 162, 255))

    # кривая недели
    gx0, gy0, gx1, gy1 = M + 44, 420, W - M - 44, 780
    if curve and len(curve) >= 2:
        pts = [0.0] + list(curve)
        lo, hi = min(min(pts), 0), max(max(pts), 0)
        span = (hi - lo) or 1.0
        xy = [(gx0 + (gx1 - gx0) * i / (len(pts) - 1),
               gy1 - (gy1 - gy0) * (v - lo) / span) for i, v in enumerate(pts)]
        zy = gy1 - (gy1 - gy0) * (0 - lo) / span
        d.line([(gx0, zy), (gx1, zy)], fill=(70, 88, 110, 160), width=2)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).line(xy, fill=(109, 174, 255, 110), width=12, joint="curve")
        bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
        d.line(xy, fill=(232, 239, 246, 255), width=4, joint="curve")
        ex, ey = xy[-1]
        d.ellipse((ex - 8, ey - 8, ex + 8, ey + 8), fill=(232, 239, 246, 255))
    else:
        d.text(((gx0 + gx1) // 2, (gy0 + gy1) // 2), "тихая неделя",
               font=F["flavor"], fill=(70, 88, 110, 255), anchor="mm")

    d.text((M + 44, 856), "Каждая сделка заявлена ДО исхода: вход, стоп, цель.",
           font=F["flavor"], fill=(182, 195, 208, 255))
    d.text((M + 44, 906), "Не согласен с цифрами - приходи и покажи свои.",
           font=F["flavor"], fill=(109, 174, 255, 255))
    d.line([(M + 44, H - M - 82), (W - M - 44, H - M - 82)],
           fill=(48, 62, 80, 255), width=2)
    d.text((M + 44, H - M - 50), f"TRADER SERIES · {season}" + (f" · {INVITE_URL}" if INVITE_URL else ""),
           font=F["footer"], fill=(133, 147, 162, 255))
    d.text((W - M - 44, H - M - 50), "VERIFIED BY DECLARATION",
           font=F["footer_b"], fill=(232, 239, 246, 255), anchor="ra")

    out = _io.BytesIO()
    bg.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


async def post_fund_card():
    """Собрать неделю из заявок и выложить карту. False, если недели не было."""
    now = datetime.now(PRAGUE)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    recs = declared_records(since=since)
    if not recs:
        adm = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
        if adm:
            try:
                await adm.send("🃏 Карта вызова: за неделю ни одной закрытой заявки - "
                               "публиковать нечего.")
            except Exception:
                pass
        return False
    s = pnl_summary(recs)
    # дисциплина недели: доля закрытых по правилам среди закрытых
    kept = sum(1 for r in recs if r["result_r"] >= -(1 + DISCIPLINE_TOL))
    disc = kept / len(recs) * 100
    run, curve = 0.0, []
    for r in recs:
        run += r["result_r"]
        curve.append(run)
    week_no = int(now.strftime("%W"))
    img = await asyncio.to_thread(
        render_fund_card, week_no, s["n"], s["total"], s["winrate"], disc,
        curve, f"S{now:%m.%y}")
    channel = bot.get_channel(NEWS_CHANNEL_ID)
    if channel:
        try:
            await channel.send(
                content="🃏 Неделя сервера одной картой. Публикуется каждое воскресенье - "
                        "можно репостить куда угодно, цифры проверяемы.",
                file=discord.File(img, f"nasdaqistan_week{week_no}.png"))
        except Exception as e:
            print(f"[fundcard] не ушла: {e}")
            return False
    return True


@tasks.loop(minutes=10)
@loop_guard("fundcard")
async def fundcard_loop():
    now = datetime.now(PRAGUE)
    week = now.strftime("%Y-W%W")
    if (now.weekday() != FUNDCARD_DAY or now.hour != FUNDCARD_HOUR
            or once_marks.get("fundcard_week") == week):
        return
    once_marks["fundcard_week"] = week
    save_runtime_state()
    await post_fund_card()


# ==================================================================
#                   ФЭНТЕЗИ-ДРАФТ ТРЕЙДЕРОВ
# ==================================================================
# Собираешь состав из трейдеров СВОЕГО сервера; их закрытые заявки за неделю -
# твои очки. MarketDraft драфтит акции; людей из своей комнаты не может драфтить
# никто - для этого нужны проверяемые заявки. Эффект двойной: болеешь за чужие
# сделки и заходишь их читать, а популярные в драфте получают статус, который
# хочется оправдывать.
#
# Включается сам только когда есть из кого выбирать (FANTASY_MIN_POOL) - до
# этого молчит, чтобы не драфтить троих из трёх.
FANTASY_STATE_FILE = "fantasy_state.json"
FANTASY_OPEN_DAY, FANTASY_OPEN_HOUR = 0, 13     # Пн 13:00
FANTASY_LOCK_DAY, FANTASY_LOCK_HOUR = 1, 13     # Вт 13:00
FANTASY_SETTLE_DAY, FANTASY_SETTLE_HOUR = 6, 20 # Вс 20:00
FANTASY_TEAM = 3
FANTASY_MIN_POOL = 4
FANTASY_PRIZE = 20
FANTASY_LOOKBACK_DAYS = 14

fantasy = {}   # {"week","stage","pool":{uid:name},"picks":{uid:[...]},"locked_at","msg_id"}


def load_fantasy():
    global fantasy
    if os.path.exists(FANTASY_STATE_FILE):
        try:
            with open(FANTASY_STATE_FILE) as f:
                fantasy = json.load(f)
        except Exception as e:
            print(f"fantasy load error: {e}")
            fantasy = {}


def save_fantasy():
    save_json_atomic(FANTASY_STATE_FILE, fantasy, "fantasy")


def fantasy_pool(guild):
    """Кого можно драфтить: закрывал заявку по-настоящему за последние 2 недели."""
    since = datetime.now(timezone.utc) - timedelta(days=FANTASY_LOOKBACK_DAYS)
    pool = {}
    for r in declared.values():
        if r.get("status") != "closed" or r.get("quick"):
            continue
        try:
            if datetime.fromisoformat(r["closed_at"]) < since:
                continue
        except Exception:
            continue
        uid = r.get("uid")
        member = guild.get_member(uid) if uid else None
        if member and not member.bot:
            pool[str(uid)] = member.display_name[:80]
    return pool


def fantasy_scores():
    """Очки менеджеров: сумма result_r заявок их состава, закрытых после лока."""
    try:
        locked_at = datetime.fromisoformat(fantasy["locked_at"])
    except Exception:
        return {}
    trader_r = {}
    for r in declared.values():
        if r.get("status") != "closed" or r.get("quick"):
            continue
        try:
            if datetime.fromisoformat(r["closed_at"]) < locked_at:
                continue
        except Exception:
            continue
        uid = str(r.get("uid"))
        trader_r[uid] = trader_r.get(uid, 0.0) + r["result_r"]
    return {mgr: round(sum(trader_r.get(t, 0.0) for t in team), 2)
            for mgr, team in fantasy.get("picks", {}).items()}


class FantasyPick(discord.ui.Select):
    def __init__(self, pool):
        options = [discord.SelectOption(label=name, value=uid)
                   for uid, name in list(pool.items())[:25]]
        super().__init__(placeholder=f"Выбери состав (до {FANTASY_TEAM} трейдеров)",
                         custom_id="fantasy_pick", min_values=1,
                         max_values=min(FANTASY_TEAM, len(options)), options=options)

    async def callback(self, interaction: discord.Interaction):
        if fantasy.get("stage") != "open":
            await interaction.response.send_message("Драфт закрыт до следующей недели.",
                                                    ephemeral=True)
            return
        fantasy.setdefault("picks", {})[str(interaction.user.id)] = list(self.values)
        save_fantasy()
        names = [fantasy["pool"].get(u, u) for u in self.values]
        await interaction.response.send_message(
            f"Состав принят: **{', '.join(names)}**.\n"
            f"Их закрытые заявки с вторника - твои очки. Пересобрать можно до лока.",
            ephemeral=True)


class FantasyView(discord.ui.View):
    def __init__(self, pool=None):
        super().__init__(timeout=None)
        if pool:
            self.add_item(FantasyPick(pool))

    @discord.ui.button(label="Мой состав", style=discord.ButtonStyle.secondary,
                       custom_id="fantasy_my", emoji="🧾", row=1)
    async def my(self, button, interaction):
        team = fantasy.get("picks", {}).get(str(interaction.user.id))
        if not team:
            await interaction.response.send_message("Ты ещё не собрал состав.",
                                                    ephemeral=True)
            return
        names = [fantasy.get("pool", {}).get(u, u) for u in team]
        text = f"Твой состав: **{', '.join(names)}**"
        if fantasy.get("stage") != "open":
            sc = fantasy_scores().get(str(interaction.user.id))
            if sc is not None:
                text += f"\nОчки на сейчас: **{sc:+.2f}R**"
        await interaction.response.send_message(text, ephemeral=True)


async def fantasy_open(channel, guild):
    pool = fantasy_pool(guild)
    if len(pool) < FANTASY_MIN_POOL:
        print(f"[fantasy] пул мал ({len(pool)}), неделя пропущена")
        return False
    embed = discord.Embed(
        title="🃏 ФЭНТЕЗИ-ДРАФТ НЕДЕЛИ",
        description=(f"Собери состав из **{FANTASY_TEAM} трейдеров сервера** - их "
                     f"закрытые заявки со вторника станут твоими очками.\n\n"
                     f"В пуле {len(pool)} "
                     f"{plural(len(pool), 'трейдер', 'трейдера', 'трейдеров')} - те, "
                     f"кто реально закрывал заявки за две недели.\n"
                     f"Лок составов: **вторник 13:00**. Итоги и приз "
                     f"+{FANTASY_PRIZE} {E_R} лучшему менеджеру: воскресенье 20:00.\n\n"
                     f"Себя брать можно. Болеть за чужие сделки - обязательно."),
        color=0xd7ecff)
    msg = await channel.send(embed=embed, view=FantasyView(pool))
    fantasy.clear()
    fantasy.update({"week": datetime.now(PRAGUE).strftime("%Y-W%W"), "stage": "open",
                    "pool": pool, "picks": {}, "msg_id": msg.id,
                    "channel_id": channel.id})
    save_fantasy()
    return True


async def fantasy_lock(channel):
    fantasy["stage"] = "locked"
    fantasy["locked_at"] = datetime.now(timezone.utc).isoformat()
    save_fantasy()
    n = len(fantasy.get("picks", {}))
    try:
        msg = await channel.fetch_message(fantasy["msg_id"])
        e = msg.embeds[0]
        e.description += f"\n\n🔒 Составы залочены: {n} " + plural(n, "менеджер", "менеджера", "менеджеров")
        await msg.edit(embed=e, view=FantasyView(None))
    except Exception as ex:
        print(f"[fantasy] лок не отредактировался: {ex}")


async def fantasy_settle(channel):
    fantasy["stage"] = "done"
    save_fantasy()
    scores = fantasy_scores()
    if not scores:
        await channel.send(embed=discord.Embed(
            title="🃏 Фэнтези: итоги", color=0xd7ecff,
            description="Составов не было. Драфт вернётся в понедельник."))
        return
    board = sorted(scores.items(), key=lambda kv: -kv[1])
    top_score = board[0][1]
    winners = [u for u, s in board if s == top_score]
    for u in winners:
        credit(int(u), FANTASY_PRIZE)
    lines = []
    for u, s in board[:10]:
        crown = "👑 " if s == top_score else "▫️ "
        team = ", ".join(fantasy["pool"].get(t, t) for t in fantasy["picks"][u])
        lines.append(f"{crown}<@{u}> — **{s:+.2f}R**  ({team})")
    lines.append(f"\nЛучшему составу +{FANTASY_PRIZE} {E_R}. Новый драфт - в понедельник.")
    await channel.send(embed=discord.Embed(title="🃏 Фэнтези: итоги недели",
                                           description="\n".join(lines), color=0xd7ecff),
                       allowed_mentions=discord.AllowedMentions(users=False))


@tasks.loop(minutes=10)
@loop_guard("fantasy")
async def fantasy_loop():
    now = datetime.now(PRAGUE)
    week = now.strftime("%Y-W%W")
    channel = bot.get_channel(NEWS_CHANNEL_ID)
    if channel is None:
        return
    at = (now.weekday(), now.hour)
    if fantasy.get("week") != week:
        if (FANTASY_OPEN_DAY, FANTASY_OPEN_HOUR) <= at < (FANTASY_LOCK_DAY, FANTASY_LOCK_HOUR):
            for guild in bot.guilds:
                await fantasy_open(channel, guild)
                break
        return
    if fantasy.get("stage") == "open" and at >= (FANTASY_LOCK_DAY, FANTASY_LOCK_HOUR):
        await fantasy_lock(channel)
    elif fantasy.get("stage") == "locked" and at >= (FANTASY_SETTLE_DAY, FANTASY_SETTLE_HOUR):
        await fantasy_settle(channel)

bot.run(TOKEN)

