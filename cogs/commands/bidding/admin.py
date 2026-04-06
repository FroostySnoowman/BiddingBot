import discord
import yaml
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional
from cogs.buttons.bidding.bid_view import BidPanelView
from cogs.functions import bidding_db
from cogs.functions.bidding_time import CHICAGO, add_months, compute_closes_at

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']

class BiddingAdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='force_start_bidding', description='Start bidding now for a target month (posts the live embed in the bidding channel).')
    @app_commands.describe(year='Target year for the slots (e.g. 2026). Omit with month.', month='Target month 1-12. Omit with year. Leave both empty for next calendar month (Chicago).')
    @app_commands.default_permissions(manage_guild=True)
    async def force_start_bidding(self, interaction: discord.Interaction, year: Optional[int] = None, month: Optional[int] = None):
        if interaction.guild_id != guild_id:
            await interaction.response.send_message('This command is not available here.', ephemeral=True)
            return

        now_chi = datetime.now(CHICAGO)
        if year is None and month is None:
            ty, tm = add_months(now_chi.year, now_chi.month, 1)
        elif year is not None and month is not None:
            if not (1 <= month <= 12):
                await interaction.response.send_message('Month must be between 1 and 12.', ephemeral=True)
                return
            ty, tm = year, month
        else:
            await interaction.response.send_message('Provide **both** year and month, or leave **both** empty to use the **next calendar month** (Chicago time).', ephemeral=True)
            return

        open_cycle = await bidding_db.get_open_cycle(guild_id)
        if open_cycle:
            await interaction.response.send_message(f'An open cycle already exists for **{open_cycle["target_year"]}-{open_cycle["target_month"]:02d}**. Close it with `/force_close_bidding` first.', ephemeral=True)
            return

        existing = await bidding_db.get_cycle_by_month(guild_id, ty, tm)
        if existing:
            await interaction.response.send_message(f'A cycle for **{ty}-{tm:02d}** already exists (phase: `{existing["phase"]}`).', ephemeral=True)
            return

        closes_chi = compute_closes_at(ty, tm)
        if now_chi >= closes_chi:
            await interaction.response.send_message(f'Bidding for **{ty}-{tm:02d}** has already ended (closed {closes_chi:%Y-%m-%d %H:%M %Z}).', ephemeral=True)
            return

        cog = interaction.client.get_cog('BiddingSchedulerCog')
        if not cog:
            await interaction.response.send_message('Scheduler not loaded.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        cid, err = await cog.start_open_cycle(ty, tm, now_chi, closes_chi)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
        await interaction.followup.send(f'Started bidding for **{ty}-{tm:02d}** (cycle #{cid}). Live message posted in the bidding channel.', ephemeral=True)

    @app_commands.command(name='force_close_bidding', description='Close the current open bidding cycle (staff).')
    @app_commands.default_permissions(manage_guild=True)
    async def force_close_bidding(self, interaction: discord.Interaction):
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