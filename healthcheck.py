"""Проверка здоровья бота. Запуск: venv/bin/python3 healthcheck.py

Главное здесь - не «запущен ли процесс», а «выдаёт ли каждая функция то, что
должна». Пост с итогом новости полтора месяца не выходил, и никто не заметил:
отсутствие сообщения не выглядит как ошибка. Эта проверка смотрит именно на
последний след каждой функции.
"""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

R = Path(__file__).parent
load_dotenv(R / ".env")
TOK = os.getenv("TOKEN")
G = os.getenv("GUILD_ID", "")
H = {"Authorization": f"Bot {TOK}", "User-Agent": "DiscordBot (local, 1.0)"}
PRAGUE, NEWYORK = ZoneInfo("Europe/Prague"), ZoneInfo("America/New_York")
NEWS, LEADER, ADMIN = (os.getenv(k, "") for k in ("NEWS_CHANNEL_ID", "LEADERBOARD_CHANNEL_ID", "ADMIN_LOG_CHANNEL_ID"))

# pm2 log of tg_parser.py
PARSER_LOG = Path(os.getenv("PARSER_LOG") or Path.home() / ".pm2/logs/tg-parser-out.log")

problems, warnings = [], []


def api(url):
    for _ in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=20))
        except Exception as e:
            if "429" in str(e):
                time.sleep(2); continue
            raise


def say(ok, name, detail="", warn=False):
    mark = "ok  " if ok else ("ВНИМАНИЕ" if warn else "ПРОБЛЕМА")
    print(f"  {mark:<9} {name}{'  ' + detail if detail else ''}")
    if not ok:
        (warnings if warn else problems).append(name)


def load(fn, default=None):
    try:
        return json.loads((R / fn).read_text())
    except Exception:
        return default


def messages(ch, limit=100):
    return api(f"https://discord.com/api/v10/channels/{ch}/messages?limit={limit}")


def last_with(msgs, needle):
    """Когда в канале последний раз появлялось сообщение с таким заголовком."""
    for m in msgs:
        for e in m.get("embeds") or []:
            if needle in (e.get("title") or "") or needle in (e.get("description") or ""):
                return datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
    return None


def age_h(dt):
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600 if dt else None


print("=" * 66)
print("  ПРОВЕРКА БОТА  ·  " + datetime.now(PRAGUE).strftime("%d.%m.%Y %H:%M"))
print("=" * 66)

# ---------- процессы ----------
print("\nПРОЦЕССЫ")
try:
    pm2 = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=20).stdout
    procs = {p["name"]: p for p in json.loads(pm2)}
    for name in ("nasdaq-bot", "tg-parser"):
        p = procs.get(name)
        if not p:
            say(False, f"{name}: не найден"); continue
        st = p["pm2_env"]["status"]
        up = (time.time() * 1000 - p["pm2_env"].get("pm_uptime", 0)) / 3600000
        restarts = p["pm2_env"].get("restart_time", 0)
        say(st == "online", f"{name}", f"{st}, аптайм {up:.1f} ч, рестартов {restarts}")
except Exception as e:
    say(False, "pm2 недоступен", str(e)[:40])

# ---------- состояние ----------
print("\nСОСТОЯНИЕ И ЭКОНОМИКА")
pts = load("points.json", {})
say(bool(pts), "points.json читается", f"{len(pts)} участников")
neg = [u for u, v in pts.items() if v.get("all", 0) - v.get("spent", 0) < 0]
say(not neg, "нет отрицательных балансов", f"{neg[:3]}" if neg else "")
bad = [u for u, v in pts.items() if v.get("week", 0) > v.get("all", 0) or v.get("month", 0) > v.get("all", 0)]
say(not bad, "недельное и месячное не больше общего", f"{bad[:3]}" if bad else "")
for fn in ("lb_state.json", "runtime_state.json", "shop_state.json",
           "bets_state.json", "session_state.json", "role_memory.json"):
    say(load(fn) is not None, f"{fn} читается", warn=True)
say(not list(R.glob("*.json.tmp")), "нет недописанных файлов")

# ---------- незакрытые ставки и игры ----------
print("\nНЕЗАКРЫТЫЕ СТАВКИ")
now = datetime.now(timezone.utc)
bets = load("bets_state.json", {})
stuck = []
for mid, b in bets.items():
    if b.get("settled"):
        continue
    try:
        ev = datetime.fromisoformat(b["dt"])
    except Exception:
        continue
    if now > ev + timedelta(minutes=60) and b.get("bets"):
        stuck.append((b["title"], (now - ev).total_seconds() / 3600, sum(x["amount"] for x in b["bets"].values())))
say(not stuck, "ставок, зависших дольше часа, нет",
    "; ".join(f"{t} ({h:.0f} ч, {r} R)" for t, h, r in stuck))
blind = load("blind_state.json", {})
overdue = [m for m, g in blind.items()
           if not g.get("settled") and datetime.fromisoformat(g["reveal_at"]) < now - timedelta(minutes=30)]
say(not overdue, "слепых графиков с просроченным вскрытием нет", f"{len(overdue)}" if overdue else "")

# ---------- функции: выдают ли они что-нибудь ----------
print("\nФУНКЦИИ ВЫДАЮТ РЕЗУЛЬТАТ")
news, adm = messages(NEWS), messages(ADMIN, 100)
checks = [
    ("утренний дайджест новостей", last_with(news, "Новости на сегодня"), 30, False),
    ("алерт перед новостью", last_with(news, "Через 15 минут"), 96, True),
    ("итог ставок", last_with(news, "Итог ставок"), 96, True),
    ("бриф открытия сессии", last_with(news, "Открытие сессии"), 96, False),
    ("итог сессии", last_with(news, "Сессия открыта"), 96, True),
    ("слепой график", last_with(news, "Слепой график"), 200, True),
    ("лог покупок в магазине", last_with(adm, "купил"), 24 * 60, True),
]
for name, when, max_h, warn in checks:
    if when is None:
        say(False, name, "следов не найдено", warn=warn); continue
    h = age_h(when)
    say(h <= max_h, name, f"последний раз {h:.0f} ч назад", warn=warn)

rt = load("runtime_state.json", {})
om = rt.get("once_marks", {})
def week_age(markkey, label):
    mark = om.get(markkey)
    if not mark:
        say(False, label, "ещё не запускался", warn=True); return
    try:
        wd = datetime.strptime(mark + "-1", "%Y-W%W-%w")
        days = (datetime.now(PRAGUE).date() - wd.date()).days
        say(days <= 8, label, f"последний запуск {days} дн назад", warn=True)
    except Exception:
        say(False, label, "битая отметка", warn=True)
week_age("arena_week", "реплей-арена")
week_age("fundcard_week", "карта вызова")
fy = load("fantasy_state.json", {})
say(bool(fy.get("week")), "фэнтези-драфт",
    f"стадия {fy.get('stage')}" if fy.get("week") else "ещё не запускался", warn=True)
pm = rt.get("once_marks", {}).get("premarket", {})
opened = pm.get("opened_day")
if opened:
    try:
        days = (datetime.now(PRAGUE).date() - datetime.fromisoformat(opened).date()).days
        say(days <= 4, "утренний премаркет", f"последний тред {days} дн назад", warn=True)
    except Exception:
        say(False, "утренний премаркет", "битая отметка", warn=True)
else:
    say(False, "утренний премаркет", "ещё не запускался", warn=True)
ech = rt.get("echoed_threads", {})
last_echo = max((datetime.fromisoformat(v) for v in ech.values() if v[:4].isdigit()), default=None)
say(last_echo is not None and age_h(last_echo) < 72, "эхо поднимало записи",
    f"{age_h(last_echo):.0f} ч назад" if last_echo else "ни разу", warn=True)

# ---------- лидерборд свежий? ----------
lb = load("lb_state.json", {}).get("lb", {})
if lb.get("all_msg"):
    m = api(f"https://discord.com/api/v10/channels/{LEADER}/messages/{lb['all_msg']}")
    edited = m.get("edited_timestamp") or m["timestamp"]
    h = age_h(datetime.fromisoformat(edited.replace("Z", "+00:00")))
    say(h < 3, "табло обновлялось", f"{h:.1f} ч назад")

# ---------- парсер ----------
print("\nПАРСЕР TELEGRAM")
try:
    log = PARSER_LOG.read_text(errors="replace").splitlines()
    fwd = [l for l in log if "Переслано" in l]
    dup = [l for l in log if "Дубль по смыслу" in l]
    fail = [l for l in log if "НЕ ОТПРАВЛЕНО" in l]
    say(bool(fwd), "пересылает сообщения", f"всего {len(fwd)}, дублей отсеяно {len(dup)}")
    say(not fail, "нет потерянных сообщений", f"{len(fail)}" if fail else "")
    mtime = datetime.fromtimestamp(PARSER_LOG.stat().st_mtime, timezone.utc)
    say(age_h(mtime) < 24, "активность за сутки есть", f"последняя запись {age_h(mtime):.0f} ч назад", warn=True)
except Exception as e:
    say(False, "лог парсера недоступен", str(e)[:40], warn=True)

# ---------- роли ----------
print("\nРОЛИ И ДОСТУПЫ")
roles = {r["name"]: r for r in api(f"https://discord.com/api/v10/guilds/{G}/roles")}
chans = api(f"https://discord.com/api/v10/guilds/{G}/channels")
VIEW = 1 << 10
def allows(rid):
    return {c["name"] for c in chans for o in c.get("permission_overwrites", [])
            if o["type"] == 0 and o["id"] == rid and int(o["allow"]) & VIEW}
try:
    nf, mb, lg = allows(roles["Newbie"]["id"]), allows(roles["Member"]["id"]), allows(roles["Legend"]["id"])
    say(not (nf - mb), "Member видит всё, что Newbie", f"{nf - mb}" if nf - mb else "")
    say(not (mb - lg), "Legend видит всё, что Member", f"{mb - lg}" if mb - lg else "")
except KeyError as e:
    say(False, f"роль не найдена: {e}")

members, after = [], "0"
while True:
    b = api(f"https://discord.com/api/v10/guilds/{G}/members?limit=1000&after={after}")
    if not b: break
    members += b; after = b[-1]["user"]["id"]
    if len(b) < 1000: break
CONC = {os.getenv(f"CONCEPT_{k}_ROLE_ID", "") for k in ("MLTF", "MP", "0DTE", "ORDERFLOW", "SWING", "PA")} - {""}
GATE = os.getenv("GATE_ROLE_ID", "")
staff = {roles["HADM"]["id"], roles["MDR"]["id"]}
hum = [m for m in members if not m["user"].get("bot")]
stuck_m = [m for m in hum if not set(m["roles"]) & CONC and GATE not in m["roles"] and not staff & set(m["roles"])]
say(not stuck_m, "нет участников без концепта и без гейта", f"{len(stuck_m)}")
both = [m for m in hum if roles["Newbie"]["id"] in m["roles"] and roles["Member"]["id"] in m["roles"]]
say(not both, "нет Newbie и Member одновременно", f"{len(both)}")

# ---------- что дальше ----------
print("\nБЛИЖАЙШИЕ СОБЫТИЯ")
now_pr = datetime.now(PRAGUE)
def nxt_hour(h):
    d = now_pr.replace(hour=h, minute=0, second=0, microsecond=0)
    return d if d > now_pr else d + timedelta(days=1)
n = datetime.now(NEWYORK)
op = n.replace(hour=9, minute=30, second=0, microsecond=0)
while n.weekday() >= 5 or op - timedelta(minutes=15) < n:
    n = (n + timedelta(days=1)).replace(hour=8, minute=0)
    op = n.replace(hour=9, minute=30, second=0, microsecond=0)
bl = now_pr.replace(hour=18, minute=0, second=0, microsecond=0)
while bl.weekday() != 2 or bl <= now_pr:
    bl += timedelta(days=1)
for label, when in sorted([
        ("утренний дайджест", nxt_hour(8)), ("эхо", nxt_hour(20)),
        ("бриф открытия", (op - timedelta(minutes=15)).astimezone(PRAGUE)),
        ("слепой график", bl),
        ("итоги недели и сводка", (now_pr + timedelta(days=(7 - now_pr.weekday()) % 7 or 7)).replace(hour=0, minute=1)),
], key=lambda x: x[1]):
    print(f"  {when:%a %d.%m %H:%M}   {label}")

print("\n" + "=" * 66)
if problems:
    print(f"  ПРОБЛЕМ: {len(problems)}")
    for p in problems: print(f"    - {p}")
if warnings:
    print(f"  предупреждений: {len(warnings)}")
    for w in warnings: print(f"    - {w}")
if not problems and not warnings:
    print("  всё в порядке")
print("=" * 66)
sys.exit(1 if problems else 0)
