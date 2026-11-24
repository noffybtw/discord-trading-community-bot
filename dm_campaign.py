"""Рассылка тем, кто сидит в choose-concept, с учётом конверсии.

  --dry   показать список, ничего не отправлять
  --send  отправить и записать снимок в dm_campaign.json
  --stat  посмотреть, сколько человек с тех пор выбрали концепт
"""
import os, re, sys, json, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(__file__).parent
load_dotenv(REPO / ".env")
TOK = os.getenv("TOKEN"); G = os.getenv("GUILD_ID", "")
H = {"Authorization": f"Bot {TOK}", "User-Agent": "DiscordBot (local, 1.0)",
     "Content-Type": "application/json"}
GATE = os.getenv("GATE_ROLE_ID", "")
GATE_CH = os.getenv("GATE_PANEL_CHANNEL_ID", "")
CONCEPTS = {os.getenv(f"CONCEPT_{k}_ROLE_ID", "") for k in ("MLTF", "MP", "0DTE", "ORDERFLOW", "SWING", "PA")} - {""}
FILE = REPO / "dm_campaign.json"
# им уже писали сегодня по другому поводу - второе письмо за пару часов это спам
# (usernames через запятую в DM_SKIP_USERNAMES)
RECENT = {u.strip() for u in os.getenv("DM_SKIP_USERNAMES", "").split(",") if u.strip()}

TEXT = (
    "Привет! 👋\n\n"
    "Сейчас тебе виден только канал выбора концепта - остальной сервер закрыт.\n\n"
    f"Чтобы открыть доступ, зайди в <#{GATE_CH}> и нажми концепт, который торгуешь: "
    "MLTF, Market Profile, 0DTE, Order Flow, Price Action или Swing. "
    "Это нужно, чтобы в сообществе было видно, кто в каком стиле работает.\n\n"
    "Сервер откроется сразу после выбора. Если не знаешь, что выбрать - рядом есть "
    "панель с коротким описанием каждого концепта."
)


def api(u, m="GET", b=None, tries=6):
    d = json.dumps(b).encode() if b is not None else None
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=H, method=m, data=d))
            raw = r.read()
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(json.loads(e.read().decode()).get("retry_after", 1) + 0.5); continue
            raise


def members():
    out, after = [], "0"
    while True:
        b = api(f"https://discord.com/api/v10/guilds/{G}/members?limit=1000&after={after}")
        if not b: break
        out += b; after = b[-1]["user"]["id"]
        if len(b) < 1000: break
    return out


def is_farm(m):
    """Признаки накрутки: зашли пачкой 09.07 и/или сгенерированное имя вида
    имяфамилия+4 цифры при свежесозданном аккаунте."""
    name = m["user"]["username"]
    joined = m["joined_at"][:10]
    uid = int(m["user"]["id"])
    created_ms = (uid >> 22) + 1420070400000
    from datetime import datetime, timezone
    created = datetime.fromtimestamp(created_ms / 1000, timezone.utc)
    j = datetime.fromisoformat(m["joined_at"].replace("Z", "+00:00"))
    fresh = (j - created).days < 10
    return bool(re.fullmatch(r"[a-z.]{6,}\d{4}", name)) and (fresh or joined == "2026-07-09")


def gated(ms):
    return [m for m in ms if GATE in m["roles"] and not m["user"].get("bot")
            and not set(m["roles"]) & CONCEPTS]


mode = "--stat" if "--stat" in sys.argv else ("--send" if "--send" in sys.argv else "--dry")

if mode == "--stat":
    if not FILE.exists():
        print("кампания ещё не запускалась"); sys.exit(0)
    data = json.loads(FILE.read_text())
    ms = {m["user"]["id"]: m for m in members()}
    stat = {"live": [0, 0, 0], "farm": [0, 0, 0]}   # выбрали / в гейте / вышли
    won = []
    for uid, info in data["targets"].items():
        k = "farm" if info.get("farm") else "live"
        m = ms.get(uid)
        if m is None:
            stat[k][2] += 1
        elif set(m["roles"]) & CONCEPTS:
            stat[k][0] += 1; won.append((k, info["name"]))
        else:
            stat[k][1] += 1
    total = len(data["targets"])
    deliv = sum(1 for i in data["targets"].values() if i["delivered"])
    print(f"КАМПАНИЯ {data['campaign']}  (отправлена {data['sent_at'][:16]} UTC)")
    print("=" * 62)
    print(f"  доставлено {deliv} из {total}\n")
    print(f"  {'':<18}{'выбрали':<10}{'в гейте':<10}{'вышли':<8}конверсия")
    for k, label in (("live", "живые люди"), ("farm", "ботоферма")):
        d, s_, l = stat[k]
        tot = d + s_ + l
        conv = f"{d/tot*100:.0f}%" if tot else "-"
        print(f"  {label:<18}{d:<10}{s_:<10}{l:<8}{conv}")
    if won:
        print("\n  вернулись после рассылки:")
        for k, n in won: print(f"    + {n}{'  (ферма)' if k=='farm' else ''}")
    sys.exit(0)

ms = members()
targets = gated(ms)
skip = [m for m in targets if m["user"]["username"] in RECENT]
send_to = [m for m in targets if m["user"]["username"] not in RECENT]

print(f"{'ОТПРАВКА' if mode=='--send' else 'СУХОЙ ПРОГОН'}")
print("=" * 60)
print(f"  в гейте всего:        {len(targets)}")
print(f"  пропускаю (писал сегодня): {len(skip)} -> {', '.join(m['user']['username'] for m in skip) or '-'}")
print(f"  адресатов:            {len(send_to)}\n")

if mode == "--dry":
    for m in send_to: print(f"    {m['user']['username']}")
    print("\n--- текст ---\n" + TEXT)
    print("\nдля отправки: --send")
    sys.exit(0)

results = json.loads(FILE.read_text())["targets"] if FILE.exists() else {}
already = {i["name"] for i in results.values() if i.get("delivered")}
if already:
    print(f"  уже получили ранее в этой кампании: {len(already)} -> пропускаю\n")
    send_to = [m for m in send_to if m["user"]["username"] not in already]
ok = fail = 0
for m in send_to:
    uid = m["user"]["id"]; name = m["user"]["username"]
    delivered = False
    try:
        dm = api("https://discord.com/api/v10/users/@me/channels", "POST", {"recipient_id": uid})
        api(f"https://discord.com/api/v10/channels/{dm['id']}/messages", "POST", {"content": TEXT})
        delivered = True; ok += 1
        print(f"  ok       {name}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:120]
        print(f"  не дошло {name}: {e.code}{' (закрыты ЛС)' if '50007' in body else ''}")
        fail += 1
    results[uid] = {"name": name, "delivered": delivered, "farm": is_farm(m)}
    time.sleep(1.2)

FILE.write_text(json.dumps({
    "campaign": "choose-concept",
    "sent_at": datetime.now(timezone.utc).isoformat(),
    "targets": results,
}, ensure_ascii=False))
print(f"\nдоставлено {ok}, не дошло {fail}")
print(f"снимок записан в {FILE}  (прогресс: --stat)")
