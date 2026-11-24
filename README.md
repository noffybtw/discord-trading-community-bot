# Discord trading community bot

The bot of a Discord server for day traders. New members pick the trading styles they use to open the server, write trades and premarket plans in forum channels, and earn points ("R") for it. The bot runs the role gate, support tickets, the points economy with a shop and an auction, an economic-calendar feed with alerts, leaderboards, trade statistics, weekly games and image cards. A second script forwards market news from a Telegram channel to Discord.

User-facing texts and code comments are in Russian (the server's language), some panels are bilingual.

## Stack

Python 3, asyncio, [py-cord](https://pycord.dev) 2.8 (slash commands, persistent buttons, modals), aiohttp, Telethon, matplotlib and Pillow for the images. State is kept in JSON files next to the scripts.

## Run

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env          # bot token, server / role / channel ids
venv/bin/python bot.py        # the Discord bot
venv/bin/python tg_parser.py  # Telegram -> Discord news forwarder, a separate process
venv/bin/python healthcheck.py
venv/bin/python dm_campaign.py --dry
```

Every Discord id (server, roles, channels, forum tags, custom emoji) comes from `.env`; an id that is not set reads as 0. Custom emoji fall back to plain Unicode emoji.

| key | what |
|---|---|
| `TOKEN` | Discord bot token |
| `GUILD_ID` | the server |
| `*_ROLE_ID`, `CONCEPT_*_ROLE_ID` | gate, status, staff, news and trading-style roles |
| `*_CHANNEL_ID`, `*_COUNTER_ID`, `TICKET_CATEGORY_ID` | log, news, leaderboard, forums, shop, counter channels |
| `SHOP_ROLE_*`, `DECLARE_TAG_*`, `CONCEPT_TAG_*` | shop roles and forum tags |
| `API_ID`, `API_HASH`, `WEBHOOK_URL`, `NEWS_GEO_ROLE_ID` | `tg_parser.py`: Telegram app keys and the Discord webhook it posts to |

## What it does

- **Role gate.** A new member sees only the "choose your concept" channel. Picking a style (MLTF, Market Profile, 0DTE, Order Flow, Price Action, Swing) gives the style role and base access; dropping the last one sends the member back to the gate. The same rules are enforced in `on_member_update`, so a role an admin changes by hand ends in the same state. Bot-made role edits are marked for 5 seconds so the handler does not undo them.
- **Reminders.** Members still in the gate get a DM 2 h and 24 h after joining, then never again. `dm_campaign.py` sends one DM to everyone still in the gate and later reports how many picked a style (`--dry`, `--send`, `--stat`).
- **Tickets.** Open, claim and close buttons; a closed ticket is saved as a transcript to an archive channel.
- **Points.** R for trades, premarkets and backtests posted in the forums, for hours in voice channels and for "thanks" replies (word-boundary patterns, daily limits per giver and per receiver). Voice time survives restarts: open sessions are saved every 5 minutes and the catch-up after a crash is capped.
- **Shop and auction.** Timed roles and colours for R; a weekly sealed-bid auction holds bids in escrow and refunds the losers. The balance is earned minus spent, while the leaderboards keep showing what was earned, so buying something never drops anyone in the ranking.
- **Economic calendar.** ForexFactory feed: a morning digest, a ping before high and medium USD events, a result post after the release, and bets on which way the market moves.
- **Declared trades.** `/trade` records instrument, entry, stop and target before the outcome is known (the direction follows from the stop). From these the bot builds the server P&L (`/pnl`), a trader card image (`/card`), an exam with a streak of kept declarations (`/exam`), a trade of the week and a fantasy draft.
- **Weekly games.** A blind chart (60 real daily candles, guess the hidden part), a Friday replay arena on 15-minute history, a weekly results card.
- **Stats for admins.** Concept statistics from thread titles (TP / SL / BE and RR), a concept league scored by the average per member, a weekly digest, a join-burst alert for groups of fresh accounts, invite tracking.
- **Leaderboards and counters.** All-time, monthly and weekly boards edited in place; three voice channels renamed to live member, trade and ticket counts.

Slash commands: `/panel`, `/conceptinfo`, `/newspanel`, `/ticketpanel`, `/statspanel`, `/shoppanel`, `/balance`, `/trade`, `/pnl`, `/card`, `/exam`, and admin-only `/givepoints`, `/checkpoints`, `/ticketsolved`, `/conceptstats`, `/digest`, `/league`.

## How it is built

- One file per process. `bot.py` is organised top to bottom by feature blocks (`# ====` banners); `on_ready` loads all state, reopens voice sessions for everyone already in a voice channel, re-registers the persistent views and starts the task loops.
- Every `tasks.loop` is wrapped in `loop_guard`: py-cord restarts a loop only after a few network exceptions, so a single Discord 5xx used to stop a loop for good.
- State is written right after every change through `load_*` / `save_*` pairs, so a restart loses nothing (daily limits, already-sent reminders, open bets).
- `tg_parser.py` classifies each post of the source channel with keyword lists (relevance, stop words, priority topics, urgent ones that ping a role) and posts matches through a Discord webhook. It shares no code with the bot.

## Tests

There are no unit tests. `healthcheck.py` checks the running server instead: that each feature left its last trace on time (the calendar result post once failed silently for weeks), that the role permissions are consistent, that no member is stuck without a style or holds two exclusive roles, and that the state files are intact.
