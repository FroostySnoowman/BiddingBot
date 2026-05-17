import discord
import yaml
from discord import app_commands
from discord.ext import commands
from cogs.buttons.tickets.panel import ApplyReviewView, PartnershipReviewView, TicketCloseView, TicketPanelView

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketCloseView())
        self.bot.add_view(ApplyReviewView())
        self.bot.add_view(PartnershipReviewView())

    @app_commands.command(name='ticketpanel', description='Post the ticket panel (admin).')
    @app_commands.default_permissions(manage_guild=True)
    async def ticketpanel(self, interaction: discord.Interaction):
        em = discord.Embed(title='Tickets', description='Choose the option that best matches what you need. The bot will create a private ticket channel for you.', color=discord.Color.from_str(embed_color))
        em.add_field(name='Staff Apply', value='Use this only if you want to apply for the staff team. This is not for requesting the SMP Owner role.', inline=False)
        em.add_field(name='Partner', value='Use this to apply for a server partnership or announcement post.', inline=False)
        em.add_field(name='Support / Bugs / General', value='Use these for help, bug reports, or other questions.', inline=False)
        await interaction.channel.send(embed=em, view=TicketPanelView())
        await interaction.response.send_message('Sent.', ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot), guilds=[discord.Object(id=guild_id)])