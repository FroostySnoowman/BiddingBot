import discord
import yaml
from discord import app_commands
from discord.ext import commands
from cogs.buttons.bidding.bid_view import BidPanelView

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']

class BiddingAdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='force_close_bidding', description='Close the current open bidding cycle (staff).')
    @app_commands.default_permissions(manage_guild=True)
    async def force_close_bidding(self, interaction: discord.Interaction):
        from cogs.functions import bidding_db

        cycle = await bidding_db.get_open_cycle(guild_id)
        if not cycle:
            await interaction.response.send_message('No open bidding cycle.', ephemeral=True)
            return
        cog = interaction.client.get_cog('BiddingSchedulerCog')
        if not cog:
            await interaction.response.send_message('Scheduler not loaded.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await cog._close_cycle(cycle)
        await interaction.followup.send('Closed and winners message posted (if channel available).', ephemeral=True)

    @app_commands.command(name='refresh_bidding_embed', description='Refresh the live bidding embed for the open cycle.')
    @app_commands.default_permissions(manage_guild=True)
    async def refresh_bidding_embed(self, interaction: discord.Interaction):
        from cogs.functions import bidding_db

        cycle = await bidding_db.get_open_cycle(guild_id)
        if not cycle:
            await interaction.response.send_message('No open cycle.', ephemeral=True)
            return
        cog = interaction.client.get_cog('BiddingSchedulerCog')
        if cog:
            await cog.refresh_live_embed_for_cycle(cycle['id'])
        await interaction.response.send_message('Refreshed.', ephemeral=True)

    @app_commands.command(name='sync_bidding_views', description='Re-register persistent bidding UI views.')
    @app_commands.default_permissions(administrator=True)
    async def sync_bidding_views(self, interaction: discord.Interaction):
        self.bot.add_view(BidPanelView())
        await interaction.response.send_message('Bid panel view registered.', ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BiddingAdminCog(bot), guilds=[discord.Object(id=guild_id)])