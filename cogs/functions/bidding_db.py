import aiosqlite
import sqlite3
from datetime import datetime, timezone
from cogs.functions.bidding_time import parse_utc_iso

DB_PATH = 'database.db'

async def get_cycle_by_month(guild_id: int, target_year: int, target_month: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT * FROM bidding_cycles
               WHERE guild_id = ? AND target_year = ? AND target_month = ?""",
            (guild_id, target_year, target_month),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

async def get_cycle_by_id(cycle_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bidding_cycles WHERE id = ?", (cycle_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def get_cycles_by_phase(guild_id: int, phase: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bidding_cycles WHERE guild_id = ? AND phase = ? ORDER BY id ASC", (guild_id, phase))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_open_cycle(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bidding_cycles WHERE guild_id = ? AND phase = 'open' ORDER BY id DESC LIMIT 1", (guild_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def insert_cycle(guild_id: int, target_year: int, target_month: int, phase: str, opens_at_utc: str, closes_at_utc: str, channel_id: int | None, live_message_id: int | None) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute("INSERT INTO bidding_cycles (guild_id, target_year, target_month, phase, opens_at_utc, closes_at_utc, channel_id, live_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (guild_id, target_year, target_month, phase, opens_at_utc, closes_at_utc, channel_id, live_message_id))
            await db.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            await db.rollback()
            return None

async def update_cycle_live_message(cycle_id: int, channel_id: int, live_message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bidding_cycles SET channel_id = ?, live_message_id = ? WHERE id = ?", (channel_id, live_message_id, cycle_id))
        await db.commit()

async def update_cycle_phase(cycle_id: int, phase: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bidding_cycles SET phase = ? WHERE id = ?", (phase, cycle_id))
        await db.commit()

async def update_cycle_winners_message(cycle_id: int, winners_message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bidding_cycles SET winners_message_id = ? WHERE id = ?", (winners_message_id, cycle_id))
        await db.commit()

async def slot_high_bids(cycle_id: int) -> dict[int, tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("WITH ranked AS (SELECT slot, user_id, amount_cents, ROW_NUMBER() OVER (PARTITION BY slot ORDER BY amount_cents DESC, created_at ASC, id ASC) AS rn FROM bids WHERE cycle_id = ? ) SELECT slot, user_id, amount_cents FROM ranked WHERE rn = 1", (cycle_id,))
        rows = await cur.fetchall()
    out: dict[int, tuple[int, int]] = {}
    for slot, user_id, amount_cents in rows:
        out[int(slot)] = (int(amount_cents), int(user_id))
    return out

async def max_bid_for_slot(cycle_id: int, slot: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT MAX(amount_cents) FROM bids WHERE cycle_id = ? AND slot = ?", (cycle_id, slot))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    return None

async def insert_bid(cycle_id: int, slot: int, user_id: int, amount_cents: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO bids (cycle_id, slot, user_id, amount_cents) VALUES (?, ?, ?, ?)", (cycle_id, slot, user_id, amount_cents))
        await db.commit()

def cycle_is_bidding_open(cycle: dict) -> bool:
    if cycle.get('phase') != 'open':
        return False
    now = datetime.now(timezone.utc)
    closes = parse_utc_iso(cycle['closes_at_utc'])
    opens = parse_utc_iso(cycle['opens_at_utc'])
    return opens <= now < closes

async def insert_invoice_row(cycle_id: int, slot: int, user_id: int, amount_cents: int, stripe_invoice_id: str, status: str = "pending"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO invoices (cycle_id, slot, user_id, amount_cents, stripe_invoice_id, status) VALUES (?, ?, ?, ?, ?, ?)", (cycle_id, slot, user_id, amount_cents, stripe_invoice_id, status))
        await db.commit()

async def mark_invoice_paid(stripe_invoice_id: str):
    paid_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE stripe_invoice_id = ?", (paid_at, stripe_invoice_id))
        await db.commit()

async def mark_invoice_paid_if_pending(stripe_invoice_id: str) -> bool:
    paid_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE stripe_invoice_id = ? AND status = 'pending'", (paid_at, stripe_invoice_id))
        await db.commit()
        return cur.rowcount > 0

async def list_pending_invoices() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM invoices WHERE status = 'pending' ORDER BY id ASC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_invoice_by_stripe_id(stripe_invoice_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM invoices WHERE stripe_invoice_id = ?", (stripe_invoice_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def cycle_invoice_count(cycle_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM invoices WHERE cycle_id = ?", (cycle_id,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0

async def invoice_exists_for_slot(cycle_id: int, slot: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM invoices WHERE cycle_id = ? AND slot = ? LIMIT 1", (cycle_id, slot))
        row = await cur.fetchone()
        return row is not None

async def next_ticket_number() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT next_num FROM ticket_counter WHERE id = 1")
        row = await cur.fetchone()
        n = int(row[0]) + 1
        await db.execute("UPDATE ticket_counter SET next_num = ? WHERE id = 1", (n,))
        await db.commit()
        return n