# Bidding Bot

A [discord.py](https://github.com/Rapptz/discord.py) bot for **monthly slot auctions** (10 slots), **Stripe invoices** (secret key + API polling—no webhook), **channel-based tickets** (Apply, Support, Bugs, General), and **simple AutoMod**. Data is stored in **SQLite** via **aiosqlite** (`database.db`).

---

## Table of contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Discord application setup](#discord-application-setup)
4. [Configuration (`config.yml`)](#configuration-configyml)
5. [How bidding works](#how-bidding-works)
6. [Stripe invoices and payment logs](#stripe-invoices-and-payment-logs)
7. [Tickets](#tickets)
8. [AutoMod](#automod)
9. [Slash commands](#slash-commands)
10. [Running the bot](#running-the-bot)
11. [Database](#database)
12. [Troubleshooting](#troubleshooting)

---

## Requirements

- **Python 3.10+** (recommended; the codebase uses modern typing syntax).
- A **Discord application** with a bot user and token.
- **Privileged intents**: the bot uses `discord.Intents.all()` in `main.py`, so in the [Discord Developer Portal](https://discord.com/developers/applications) enable **Server Members Intent** and **Message Content Intent** for your bot.
- **`tzdata`** is listed in `requirements.txt` so `zoneinfo` has IANA data on Windows/macOS if the OS lacks it.

Install dependencies from the project root:

```bash
python3 -m pip install -r requirements.txt
```

---

## Installation

1. Clone or copy this repository.
2. Create and fill `config.yml` (see below). **Do not commit real tokens or secrets**; add `config.yml` to `.gitignore` if you store secrets there, or use a private deploy path.
3. Install requirements (command above).
4. Invite the bot to your server with the permissions listed in [Discord application setup](#discord-application-setup).
5. Set `General.GUILD_ID` to your server’s ID (Developer Mode → right‑click server → Copy Server ID).
6. Adjust `owner_ids` in `main.py` if you want specific users to have bot owner checks (optional; used by discord.py’s owner checks).

---

## Discord application setup

1. **Create an application** → **Bot** → reset/copy **token** → paste into `General.TOKEN` in `config.yml`.
2. Under **Privileged Gateway Intents**, enable:
   - **Presence Intent**,
   - **Server Members Intent**,
   - **Message Content Intent**.
3. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`. Suggested bot permissions:
   - **Manage Channels** (create ticket channels),
   - **Manage Roles** (optional; only if you automate roles),
   - **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History**,
   - **Manage Messages** (AutoMod deletions),
   - **Create Private Threads** (not required for current channel-only tickets),
   - **Moderate Members** (optional),
   - **Use Slash Commands**.

Exact needs depend on your server; if something fails, check the error and grant the missing permission.

4. After the bot joins, slash commands are **synced globally and to your guild** in `on_ready` (see `main.py`). The first sync after a change can take up to an hour globally; guild sync is usually fast.

---

## Configuration (`config.yml`)

All runtime options are read from **`config.yml`** in the working directory (same folder you run `main.py` from).

### `General`

| Key | Purpose |
|-----|--------|
| `TOKEN` | Discord bot token. |
| `ACTIVITY` | One of: `playing`, `watching`, `listening`, `streaming`. |
| `DOING_ACTIVITY` | Text shown in the activity (required except for modes that don’t need it—see `main.py` validation). |
| `STREAMING_ACTIVITY_TWITCH_URL` | Required if `ACTIVITY` is `streaming` (must contain `https://twitch.tv/`). |
| `STATUS` | One of: `online`, `idle`, `dnd`, `invisible`. |
| `EMBED_COLOR` | Hex color for embeds, e.g. `"#9C27B0"`. |
| `GUILD_ID` | Your Discord server ID (integer). Most features only run in this guild. |

### `Bidding`

| Key | Purpose |
|-----|--------|
| `CHANNEL_ID` | Text channel where the **live bidding embed** is posted and **winners** are announced. If `0`, the scheduler **will not** auto-post a new cycle (useful for testing without a channel). |
| `BIDDER_ROLE_ID` | Users **without** this role cannot place bids. Set `0` to disable the role check (everyone in the server could bid—usually not desired). |
| `MIN_BID_CENTS` | Minimum bid in **cents** (e.g. `100` = $1.00). |
| `OPENS_HOUR_CHICAGO` | Hour **0–23** on the calendar day when the auction **opens** (Chicago time). Opening moment = that hour on **(first day of target month − 14 days)**. |
| `STAFF_FALLBACK_CHANNEL_ID` | Staff-visible channel for Stripe errors, failed DMs, or “Stripe not configured” notices. Can be `0` to skip (not recommended in production). |

### `Stripe`

| Key | Purpose |
|-----|--------|
| `SECRET_KEY` | Stripe **secret** API key (`sk_live_...` or `sk_test_...`). You may alternatively use **`STRIPE_API_KEY`** as the key name (same value)—the code accepts either. |
| `INVOICE_DAYS_UNTIL_DUE` | Days until the hosted invoice is due (Stripe `send_invoice`). |

There is **no webhook**. Paid status is detected by **polling** `stripe.Invoice.retrieve` every **2 minutes** (see `cogs/events/stripe_poll.py`).

### `Channels`

| Key | Purpose |
|-----|--------|
| `INVOICE_LOG_CHANNEL_ID` | Text channel where **“invoice paid”** embeds are posted after Stripe marks an invoice paid. `0` disables posting (invoices still update in the DB). |

### `Tickets`

| Key | Purpose |
|-----|--------|
| `PANEL_CHANNEL_ID` | **Documentation only** for you—where to run `/ticketpanel`. The bot does not read this key; it’s a reminder. |
| `TICKET_CATEGORY_ID` | **Category** under which new **ticket text channels** are created. |
| `STAFF_ROLE_IDS` | List of role IDs that can see tickets, get pings on open, and use the **Close** button. |
| `CATEGORIES` | Display names for the four ticket types (`apply`, `support`, `bugs`, `general`). |

### `AutoMod`

| Key | Purpose |
|-----|--------|
| `ENABLED` | `true` / `false` for the whole listener. |
| `LOG_CHANNEL_ID` | Text channel for violation logs (`0` = no log). |
| `BYPASS_ROLE_IDS` | Roles that skip AutoMod. |
| `BLOCK_INVITES` | Delete messages matching Discord invite URLs. |
| `BLOCKED_WORDS` | Substrings (lowercased match). |
| `MAX_MENTIONS` | Max user + role mentions per message. |
| `FLOOD_MESSAGES` / `FLOOD_SECONDS` | Max messages per user per channel in a sliding window. |
| `MAX_CAPS_RATIO` | For messages with enough letters, caps ratio above this triggers deletion. |

**Note:** Users with **Manage Messages** or **Administrator** always bypass AutoMod.

---

## How bidding works

### Target month and timezone

- Bidding is for a **target calendar month** \(M\) (the “upcoming month” slots).
- All **open/close scheduling** uses **`America/Chicago`** (handles CST/CDT).

### Open and close times

- **Opens:** **14 days before** the first day of month **M**, at **`OPENS_HOUR_CHICAGO`** (0–23) on that calendar day in Chicago.
- **Closes:** **24 hours before** the start of month **M** in Chicago (i.e. `first_moment_of_M − 24 hours`).

Example: for **April** slots, bidding opens on **March 18** at the configured hour (if `OPENS_HOUR_CHICAGO` is `0`, that is midnight Chicago on March 18). It closes at **March 31, 00:00 Chicago** (24 hours before April 1, 00:00).

### What the bot posts

1. **During the window:** A **live embed** in `Bidding.CHANNEL_ID` lists **Slot 1–10** with current high bids. A **persistent** dropdown lets eligible users pick a slot and enter a **USD** amount in a modal.
2. **After close:** A **new message** in the same channel lists **winners**: `SLOT n — @user ($amount)` or “no bids” for empty slots.
3. **Bidding rules (high level):**
   - Must have the **bidder role** (if `BIDDER_ROLE_ID` is non-zero).
   - Bid must be **≥ `MIN_BID_CENTS`**.
   - New bid on a slot must be **strictly higher** than the current high.
   - **Tie-break:** same high amount → earlier bid wins (see SQL window in `bidding_db.slot_high_bids`).

### Scheduler

- `cogs/events/bidding_scheduler.py` runs a loop about every **2 minutes**: refreshes open embeds, closes cycles when past `closes_at_utc`, creates **Stripe invoices** and DMs winners, and advances cycle phase when invoicing is complete.
- If **`Stripe.SECRET_KEY`** is empty, winners are still posted; the cycle is marked **invoiced** without payment links, and a notice may go to `STAFF_FALLBACK_CHANNEL_ID`.

### Phases (database)

- **`open`:** accepting bids; live message exists.
- **`closed`:** winners posted; invoicing in progress or retrying.
- **`invoiced`:** invoicing finished (all winning slots have invoice rows when Stripe is configured, or skipped when Stripe is off).

---

## Stripe invoices and payment logs

1. After winners are determined, the bot creates a **Stripe Customer** and **Invoice** (plus line item) per winning slot, **finalizes** the invoice, and DMs the **hosted invoice URL**.
2. A row is stored in SQLite **`invoices`** with `status = pending`.
3. **`stripe_poll`** checks pending rows every **2 minutes** with `Invoice.retrieve`. When `paid` is true, the row is updated to **paid** (only once) and an embed is sent to **`INVOICE_LOG_CHANNEL_ID`**.

**Stripe Dashboard:** ensure your account can create **invoices** and that **customer email** requirements match how you use Stripe (the bot creates customers with metadata; email is optional depending on your Stripe settings).

---

## Tickets

1. A user with **Manage Server** runs **`/ticketpanel`** in the channel where you want the panel (often the channel ID you noted in `PANEL_CHANNEL_ID`).
2. Users click **Apply**, **Support**, **Bugs**, or **General**, fill the **modal**, and the bot creates a **private text channel** under **`TICKET_CATEGORY_ID`** named like `apply-42`.
3. **Permissions:** `@everyone` cannot view the channel; the opener and **`STAFF_ROLE_IDS`** can. The first message pings the opener and staff roles.
4. Staff use the **Close** button to **delete** the channel (only users with **Manage Guild**, **Administrator**, or a configured staff role).

---

## AutoMod

Runs on **normal messages** in **`GUILD_ID`** only. Deletes the message on violation and optionally logs to **`LOG_CHANNEL_ID`**. Configure rules under **`AutoMod`** in `config.yml` (see table above).

---

## Slash commands

| Command | Who | Description |
|--------|-----|-------------|
| `/ticketpanel` | Manage Server | Posts the ticket panel embed + buttons. |
| `/force_close_bidding` | Manage Server | Closes the **current open** bidding cycle immediately (posts winners, then invoicing follows as usual). |
| `/refresh_bidding_embed` | Manage Server | Rebuilds the **live** bidding embed from the database. |
| `/sync_bidding_views` | Administrator | Re-registers the **persistent** bid dropdown view (use after restarts/deploys if interactions break). |

Prefix commands: the bot uses `commands.when_mentioned_or('.')` but the main features are **slash commands**.

---

## Running the bot

From the project directory:

```bash
python3 main.py
```

On first run, **`check_tables()`** in `setup_hook` creates **`database.db`** and tables if missing.

Keep the process online (systemd, pm2, Docker, a VPS screen/tmux session, etc.) so scheduling and Stripe polling keep running.

---

## Database

- **File:** `database.db` (SQLite).
- **Tables:** `bidding_cycles`, `bids`, `invoices`, `ticket_counter` (see `cogs/functions/sqlite.py`).
- **Backup:** copy `database.db` while the bot is stopped or use SQLite backup tools.

---

## Troubleshooting

| Issue | Things to check |
|-------|------------------|
| Slash commands missing | Bot invited with `applications.commands`; wait for sync; ensure `GUILD_ID` matches; re-invite if needed. |
| “Bidding is not open” | Outside Chicago window; or no **`open`** cycle in DB; or phase already **closed** / **invoiced**. |
| No auto bidding post | `Bidding.CHANNEL_ID` must be **non-zero** and a valid text channel the bot can write to. |
| Dropdown does nothing after update | Run **`/sync_bidding_views`** as Administrator; restart bot after code changes. |
| Stripe invoice errors | Secret key, Stripe dashboard restrictions, currency USD; check **`STAFF_FALLBACK_CHANNEL_ID`**. |
| Paid but no log message | `INVOICE_LOG_CHANNEL_ID` non-zero; bot can **Send Messages** there; wait up to ~2 minutes for poll. |
| Ticket channel not created | `TICKET_CATEGORY_ID` is a **category** ID; bot has **Manage Channels**. |
| AutoMod too aggressive | Raise thresholds, add **`BYPASS_ROLE_IDS`**, or set **`ENABLED: false`**. |

---

## Project layout (high level)

- `main.py` — bot entry, intents, extension load order, `check_tables()`.
- `config.yml` — all configuration.
- `cogs/functions/sqlite.py` — schema creation.
- `cogs/functions/bidding_db.py` — bidding / invoice / ticket counter queries.
- `cogs/functions/bidding_time.py` — Chicago open/close math.
- `cogs/functions/stripe_invoices.py` — create invoices + `Invoice.retrieve` helper.
- `cogs/events/bidding_scheduler.py` — bidding lifecycle task loop.
- `cogs/events/stripe_poll.py` — paid-invoice polling + log channel posts.
- `cogs/buttons/bidding/bid_view.py` — persistent select + bid modal + embed builder.
- `cogs/commands/bidding/admin.py` — staff slash commands for bidding.
- `cogs/buttons/tickets/panel.py` — ticket modals, channel creation, close view.
- `cogs/commands/tickets/tickets.py` — `/ticketpanel`.
- `cogs/events/automod.py` — AutoMod listener.

---

## License

Add your preferred license if you distribute this project.
