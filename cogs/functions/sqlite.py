import aiosqlite

async def check_tables():
    async with aiosqlite.connect('database.db') as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bidding_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_year INTEGER NOT NULL,
                target_month INTEGER NOT NULL,
                phase TEXT NOT NULL DEFAULT 'scheduled',
                opens_at_utc TEXT NOT NULL,
                closes_at_utc TEXT NOT NULL,
                channel_id INTEGER,
                live_message_id INTEGER,
                winners_message_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(guild_id, target_year, target_month)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                slot INTEGER NOT NULL CHECK(slot >= 1 AND slot <= 10),
                user_id INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (cycle_id) REFERENCES bidding_cycles(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                stripe_invoice_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                paid_at TEXT,
                FOREIGN KEY (cycle_id) REFERENCES bidding_cycles(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_num INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("INSERT OR IGNORE INTO ticket_counter (id, next_num) VALUES (1, 0)")
        await db.commit()