from telethon import TelegramClient, events
import aiohttp
import asyncio
import os
import re
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ================== CONFIG ==================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL = "markettwits"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
NEWS_GEO_ROLE_ID = int(os.getenv("NEWS_GEO_ROLE_ID") or 0)  # роль NewsGeo для срочных

# Термины ищутся ПО ГРАНИЦАМ СЛОВ, а не подстрокой.
# "слово"  - только целиком ("сво" не поймает "свои", "свободно", "сводка")
# "слово*" - слово с любым окончанием ("иран*" ловит иран, ирана, иранский)
# Пробел внутри термина означает любое количество пробелов.

# --- ключевые темы (что вообще нас интересует) ---
KEYWORDS = [
    "иран*", "iran*", "израил*", "israel*", "газа", "gaza",
    "трамп*", "trump*", "белый дом",
    "нефт*", "oil", "brent", "wti", "опек", "opec",
    "фрс", "fed", "пауэлл*", "powell",
    "ракет*", "хезболл*", "hezbollah", "хусит*", "houthi*",
    "ядерн*", "nuclear",
    "пошлин*", "tariff*", "ближн* восток",
    "сша", "usa",
]

# --- приоритетные темы: пропускаем даже при наличии стоп-слова ---
PRIORITY = [
    "иран*", "iran*", "израил*", "israel*", "газа", "gaza",
    "трамп*", "trump*", "нефт*", "oil", "brent", "wti",
    "опек", "opec", "фрс", "fed", "пауэлл*", "powell",
    "хезболл*", "hezbollah", "хусит*", "houthi*", "ядерн*", "nuclear",
    "пошлин*", "tariff*",
]

# --- срочные маркеры: если есть - помечаем и ПИНГУЕМ ---
URGENT = [
    "срочно", "breaking", "молни*", "экстренн*",
    "удар*", "атаков*", "атака", "ударил*",
    "взрыв*", "обстрел*", "вторжени*", "погиб*", "убит*",
    "эвакуац*", "тревог*", "объявил войну",
    "перехвачен*", "сбит*", "сбил*", "ракетн*",
]

# --- стоп-слова: режем, если нет приоритетной темы ---
# "сво", "всу", "вс рф" - аббревиатуры, поэтому только целым словом
STOP_WORDS = [
    "росси*", "russia*", "путин*", "putin*", "кремл*", "kremlin",
    "украин*", "ukraine*", "зеленск*", "zelensky", "киев*", "kyiv",
    "сво", "всу", "вс рф", "мобилизац*", "вооруж*",
    "vk", "вконтакте", "роскомнадзор",
]

# --- реклама и служебные посты канала ---
ADS = [
    "реклама", "рекламодател*", "erid", "партнёрск*", "партнерск*",
    "промокод*", "подписывайт*", "розыгрыш*", "вебинар*",
]

# --- дедуп по смыслу ---
# Канал выдаёт одно событие несколькими сообщениями подряд: 298 из 441 пересылок
# шли с разрывом id <= 3. Сравниваем набор значимых слов с недавно отправленным.
DEDUP_WINDOW_MIN = 20
DEDUP_OVERLAP = 0.55
NOISE = {
    "сообщает", "заявил", "заявила", "сообщил", "сообщила", "агентство", "источник",
    "источники", "также", "после", "более", "менее", "может", "могут", "будет",
    "были", "было", "этом", "этой", "которые", "который", "года", "году", "процента",
    "процентов", "стало", "стали", "своей", "своих", "против", "около",
}

# --- вечерняя сводка ---
DIGEST_HOUR = 21        # час по европейскому времени; None отключает
PRAGUE = ZoneInfo("Europe/Prague")

MAX_LEN = 1850          # лимит текста в сообщении Discord
MAX_POSTED_IDS = 2000   # сколько id держим для дедупа
WEBHOOK_RETRIES = 3
# ============================================


def term_to_pattern(term):
    """'сво' -> \\bсво\\b, 'иран*' -> \\bиран\\w*, 'вс рф' -> \\bвс\\s+рф\\b"""
    prefix = term.endswith("*")
    if prefix:
        term = term[:-1]
    body = r"\s+".join(re.escape(w) for w in term.split())
    return rf"\b{body}" + (r"\w*" if prefix else r"\b")


def compile_terms(terms):
    return re.compile("|".join(term_to_pattern(t) for t in terms), re.IGNORECASE)


RE_KEYWORDS = compile_terms(KEYWORDS)
RE_PRIORITY = compile_terms(PRIORITY)
RE_URGENT = compile_terms(URGENT)
RE_STOP = compile_terms(STOP_WORDS)
RE_ADS = compile_terms(ADS)

recent_posts = deque()   # (время, набор слов) недавно отправленного
day_log = []             # (время, уровень, первая строка) для вечерней сводки

client = TelegramClient("markettwits_session", API_ID, API_HASH)
posted_ids = OrderedDict()   # id -> True, с ограничением размера
http = None                  # общая aiohttp-сессия, создаётся на старте


def remember(msg_id):
    posted_ids[msg_id] = True
    while len(posted_ids) > MAX_POSTED_IDS:
        posted_ids.popitem(last=False)


def significant_tokens(text):
    words = re.findall(r"[а-яёa-z]{4,}", text.lower())
    return {w for w in words if w not in NOISE}


def is_duplicate(text):
    """Похоже ли на то, что уже отправляли за последние DEDUP_WINDOW_MIN минут."""
    now = datetime.now(timezone.utc)
    while recent_posts and (now - recent_posts[0][0]) > timedelta(minutes=DEDUP_WINDOW_MIN):
        recent_posts.popleft()
    toks = significant_tokens(text)
    if len(toks) < 4:
        return False        # слишком короткое, чтобы судить о совпадении
    for _, prev in recent_posts:
        if not prev:
            continue
        # делим на меньший набор: короткая заметка внутри длинной - тоже дубль
        overlap = len(toks & prev) / min(len(toks), len(prev))
        if overlap >= DEDUP_OVERLAP:
            return True
    return False


def remember_post(text):
    recent_posts.append((datetime.now(timezone.utc), significant_tokens(text)))


def classify(text):
    """returns: 'urgent', 'normal', or None (skip)"""
    if not text or not text.strip():
        return None
    if RE_ADS.search(text):
        return None

    has_priority = bool(RE_PRIORITY.search(text))
    if has_priority:
        allow = True
    elif RE_STOP.search(text):
        allow = False
    else:
        allow = bool(RE_KEYWORDS.search(text))

    if not allow:
        return None
    # Пинг роли только когда срочный маркер совпал с приоритетной темой.
    # Раньше пинговало любое слово вроде "удар" в любом контексте.
    if RE_URGENT.search(text) and has_priority:
        return "urgent"
    return "normal"


async def forward(text, msg_id, level):
    if msg_id in posted_ids:
        return
    if is_duplicate(text):
        print(f"Дубль по смыслу, пропуск: msg {msg_id}")
        remember(msg_id)
        return

    content = text[:MAX_LEN] + ("..." if len(text) > MAX_LEN else "")
    if level == "urgent":
        payload = {
            "content": f"\U0001F6A8 <@&{NEWS_GEO_ROLE_ID}>\n{content}",
            "allowed_mentions": {"parse": ["roles"]},
        }
    else:
        payload = {"content": content, "allowed_mentions": {"parse": []}}

    # id помечаем отправленным ТОЛЬКО после успеха: иначе сбой вебхука
    # навсегда терял сообщение, потому что повтор считал его уже отправленным
    for attempt in range(WEBHOOK_RETRIES):
        try:
            async with http.post(WEBHOOK_URL, json=payload,
                                 timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    body = await resp.json(content_type=None)
                    await asyncio.sleep(float(body.get("retry_after", 1)) + 0.5)
                    continue
                if resp.status < 300:
                    remember(msg_id)
                    remember_post(text)
                    day_log.append((datetime.now(PRAGUE), level, text.strip().split("\n")[0][:110]))
                    print(f"Переслано [{level}]: msg {msg_id}")
                    return
                print(f"webhook {resp.status} на msg {msg_id}, попытка {attempt + 1}")
        except Exception as e:
            print(f"webhook error на msg {msg_id} (попытка {attempt + 1}): {e}")
        await asyncio.sleep(2 * (attempt + 1))

    print(f"НЕ ОТПРАВЛЕНО: msg {msg_id} после {WEBHOOK_RETRIES} попыток")


@client.on(events.NewMessage(chats=CHANNEL))
async def handler(event):
    level = classify(event.message.message or "")
    if level:
        await forward(event.message.message, event.message.id, level)


@client.on(events.MessageEdited(chats=CHANNEL))
async def edit_handler(event):
    level = classify(event.message.message or "")
    if level:
        await forward(event.message.message, event.message.id, level)


def plural(n, one, few, many):
    """1 новость / 2 новости / 5 новостей"""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def build_digest():
    if not day_log:
        return None
    urgent = [x for x in day_log if x[1] == "urgent"]
    lines = [f"**Сводка за {datetime.now(PRAGUE):%d.%m}** · {len(day_log)} "
             f"{plural(len(day_log), 'новость', 'новости', 'новостей')}"]
    if urgent:
        lines.append("")
        lines.append("**Срочное:**")
        for t, _, head in urgent[:6]:
            lines.append(f"· {t:%H:%M} - {head}")
    rest = [x for x in day_log if x[1] != "urgent"]
    if rest:
        lines.append("")
        lines.append("**Остальное:**")
        for t, _, head in rest[-10:]:
            lines.append(f"· {t:%H:%M} - {head}")
    return "\n".join(lines)[:MAX_LEN]


async def digest_loop():
    """Раз в день собирает всё пережитое за сутки в один пост.

    Тем, кто не сидит в чате постоянно, одна сводка полезнее ленты из 36 сообщений.
    """
    if DIGEST_HOUR is None:
        return
    posted_for = None
    while True:
        await asyncio.sleep(60)
        now = datetime.now(PRAGUE)
        if now.hour != DIGEST_HOUR or posted_for == now.date():
            continue
        posted_for = now.date()
        text = build_digest()
        day_log.clear()
        if not text:
            continue
        try:
            async with http.post(WEBHOOK_URL,
                                 json={"content": text, "allowed_mentions": {"parse": []}},
                                 timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"Сводка дня отправлена, статус {resp.status}")
        except Exception as e:
            print(f"сводка дня не ушла: {e}")


async def main():
    global http
    http = aiohttp.ClientSession()
    try:
        await client.start()
        print("Парсер запущен, слушаю @" + CHANNEL)
        asyncio.create_task(digest_loop())
        await client.run_until_disconnected()
    finally:
        await http.close()


if __name__ == "__main__":
    asyncio.run(main())
