import discord
import yaml
from discord import app_commands
from discord.ext import commands

with open('config.yml', 'r') as file:
    data = yaml.safe_load(file)

guild_id = data['General']['GUILD_ID']
embed_color = data['General']['EMBED_COLOR']

class TestCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name='test', description='Test command')
    async def test_command(self, interaction: discord.Interaction):
        ...

async def setup(bot: commands.Bot):
    await bot.add_cog(TestCog(bot), guilds=[discord.Object(id=guild_id)])