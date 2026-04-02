import discord
import yaml
from discord import app_commands
from discord.ext import commands
from cogs.buttons.tickets.panel import TicketCloseView, TicketPanelView

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketCloseView())

    @app_commands.command(name='ticketpanel', description='Post the ticket panel (admin).')
    @app_commands.default_permissions(manage_guild=True)
    async def ticketpanel(self, interaction: discord.Interaction):
        em = discord.Embed(title='Tickets', description='Choose a category below. You will answer a short form and a private ticket channel will be created.', color=discord.Color.from_str(embed_color))
        await interaction.channel.send(embed=em, view=TicketPanelView())
        await interaction.response.send_message('Sent.', ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot), guilds=[discord.Object(id=guild_id)])