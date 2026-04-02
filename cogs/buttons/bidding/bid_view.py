import discord
import re
import yaml
from discord.ext import commands
from cogs.functions import bidding_db
from cogs.functions.bidding_time import compute_closes_at, parse_utc_iso

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
bidder_role_id = _cfg.get('Bidding', {}).get('BIDDER_ROLE_ID', 0)
min_bid_cents = _cfg.get('Bidding', {}).get('MIN_BID_CENTS', 100)

class BidAmountModal(discord.ui.Modal, title='Place bid'):
    amount = discord.ui.TextInput(
        label='Amount (USD)',
        placeholder='e.g. 25.00',
        required=True,
        max_length=12,
    )

    def __init__(self, slot: int):
        super().__init__()
        self.slot = slot

    async def on_submit(self, interaction: discord.Interaction):
        cycle = await bidding_db.get_open_cycle(guild_id)
        if not cycle or not bidding_db.cycle_is_bidding_open(cycle):
            await interaction.response.send_message('Bidding is not open right now.', ephemeral=True)
            return

        if bidder_role_id and interaction.guild:
            role = interaction.guild.get_role(bidder_role_id)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message('You need the bidder role to place a bid.', ephemeral=True)
                return

        raw = self.amount.value.strip().replace(',', '')
        if not re.match(r'^\d+(\.\d{1,2})?$', raw):
            await interaction.response.send_message('Enter a valid dollar amount (e.g. 10 or 10.50).', ephemeral=True)
            return

        dollars = float(raw)
        amount_cents = int(round(dollars * 100))
        if amount_cents < min_bid_cents:
            await interaction.response.send_message(f'Bid must be at least ${min_bid_cents / 100:.2f}.', ephemeral=True)
            return

        prev = await bidding_db.max_bid_for_slot(cycle['id'], self.slot)
        if prev is not None and amount_cents <= prev:
            await interaction.response.send_message(f'Your bid must be higher than the current high (${prev / 100:.2f}).', ephemeral=True)
            return

        await bidding_db.insert_bid(cycle['id'], self.slot, interaction.user.id, amount_cents)

        closes_utc = parse_utc_iso(cycle['closes_at_utc'])
        ty, tm = cycle['target_year'], cycle['target_month']
        closes_chi = compute_closes_at(ty, tm)
        local_line = discord.utils.format_dt(closes_utc, style='F')
        chi_line = closes_chi.strftime('%Y-%m-%d %H:%M %Z')

        await interaction.response.send_message(f'Bid recorded: **Slot {self.slot}** — **${amount_cents / 100:.2f}**\nAuction ends: {local_line} (your Discord time)\nChicago reference: **{chi_line}**', ephemeral=True)

        cog = interaction.client.get_cog('BiddingSchedulerCog')
        if cog:
            await cog.refresh_live_embed_for_cycle(cycle['id'])

class BidPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder='Choose a slot (1-10)',
        custom_id='bidding_bid_slot',
        options=[
            discord.SelectOption(label=f'Slot {i}', value=str(i), description=f'Bid on slot {i}')
            for i in range(1, 11)
        ],
    )
    async def slot_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.guild_id != guild_id:
            await interaction.response.send_message('Wrong server.', ephemeral=True)
            return
        slot = int(select.values[0])
        await interaction.response.send_modal(BidAmountModal(slot))

def build_live_embed(target_year: int, target_month: int, highs: dict, closes_at_utc_str: str):
    lines = []
    for s in range(1, 11):
        if s in highs:
            cents, _uid = highs[s]
            lines.append(f'Slot {s} — ${cents / 100:.2f}')
        else:
            lines.append(f'Slot {s} — $0.00')

    closes_utc = parse_utc_iso(closes_at_utc_str)
    title = f'Upcoming month\'s slot bidding ({target_year}-{target_month:02d})'
    desc = '\n'.join(lines) + '\n\nSelect a slot below to place a bid (must beat the current high).'
    em = discord.Embed(title=title, description=desc, color=discord.Color.from_str(embed_color))
    em.add_field(name='Auction Ends', value=f'{discord.utils.format_dt(closes_utc, style="F")}\n' f'Chicago: {compute_closes_at(target_year, target_month).strftime("%Y-%m-%d %H:%M %Z")}', inline=False)
    return em

class BidViewCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(BidPanelView())

async def setup(bot: commands.Bot):
    await bot.add_cog(BidViewCog(bot), guilds=[discord.Object(id=guild_id)])