import discord
import aiosqlite
import sqlite3
import yaml
from discord.ext import commands

with open('config.yml', 'r') as file:
    data = yaml.safe_load(file)

guild_id = data["General"]["GUILD_ID"]

async def check_tables():
    await freelancer_profile_tables()

async def freelancer_profile_tables(delete: bool = False):
    async with aiosqlite.connect('database.db') as db:
        if delete:
            try:
                await db.execute('DROP TABLE freelancer_profiles')
                await db.commit()
            except sqlite3.OperationalError:
                pass
        try:
            await db.execute('SELECT * FROM freelancer_profiles')
        except sqlite3.OperationalError:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS freelancer_profiles (
                    user_id INTEGER PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT '',
                    portfolio TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timezone_set INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.commit()

class SQLiteCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot):
    await bot.add_cog(SQLiteCog(bot), guilds=[discord.Object(id=guild_id)])