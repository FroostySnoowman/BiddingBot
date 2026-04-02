import discord
import yaml
from datetime import datetime, timezone
from discord.ext import commands, tasks
from cogs.buttons.bidding.bid_view import BidPanelView, build_live_embed
from cogs.functions import bidding_db
from cogs.functions.bidding_time import CHICAGO, chicago_to_utc_iso, compute_closes_at, compute_opens_at, find_target_month_in_open_window, parse_utc_iso
from cogs.functions import stripe_invoices

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
bidding_channel_id = _cfg.get('Bidding', {}).get('CHANNEL_ID', 0) or 0
opens_hour = int(_cfg.get('Bidding', {}).get('OPENS_HOUR_CHICAGO', 0))
fallback_channel_id = _cfg.get('Bidding', {}).get('STAFF_FALLBACK_CHANNEL_ID', 0) or 0

class BiddingSchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bidding_tick.start()

    async def cog_unload(self):
        self.bidding_tick.cancel()

    async def refresh_live_embed_for_cycle(self, cycle_id: int):
        cycle = await bidding_db.get_cycle_by_id(cycle_id)
        if not cycle or not cycle.get('live_message_id') or not cycle.get('channel_id'):
            return
        ch = self.bot.get_channel(cycle['channel_id'])
        if not ch or not isinstance(ch, discord.abc.Messageable):
            return
        try:
            msg = await ch.fetch_message(cycle['live_message_id'])
        except (discord.NotFound, discord.HTTPException):
            return
        highs = await bidding_db.slot_high_bids(cycle_id)
        em = build_live_embed(cycle['target_year'], cycle['target_month'], highs, cycle['closes_at_utc'])
        try:
            await msg.edit(embed=em, view=BidPanelView())
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=2)
    async def bidding_tick(self):
        await self.bot.wait_until_ready()
        try:
            await self._run_bidding_logic()
        except Exception as e:
            print(f'[bidding_scheduler] error: {e!r}')

    @bidding_tick.before_loop
    async def before_bidding_tick(self):
        await self.bot.wait_until_ready()

    async def _run_bidding_logic(self):
        g = self.bot.get_guild(guild_id)
        if not g:
            return

        for row in await bidding_db.get_cycles_by_phase(guild_id, 'open'):
            closes = parse_utc_iso(row['closes_at_utc'])
            if datetime.now(timezone.utc) >= closes:
                await self._close_cycle(row)
            else:
                await self.refresh_live_embed_for_cycle(row['id'])

        for row in await bidding_db.get_cycles_by_phase(guild_id, 'closed'):
            await self._invoice_cycle(row)

        if bidding_channel_id == 0:
            return

        now_chi = datetime.now(CHICAGO)
        found = find_target_month_in_open_window(now_chi, opens_hour)
        if not found:
            return
        ty, tm = found
        existing = await bidding_db.get_cycle_by_month(guild_id, ty, tm)
        if existing:
            return

        opens_chi = compute_opens_at(ty, tm, opens_hour)
        closes_chi = compute_closes_at(ty, tm)
        if not (opens_chi <= now_chi < closes_chi):
            return

        ch = self.bot.get_channel(bidding_channel_id)
        if not ch or not isinstance(ch, discord.TextChannel):
            return

        opens_iso = chicago_to_utc_iso(opens_chi)
        closes_iso = chicago_to_utc_iso(closes_chi)
        em = build_live_embed(ty, tm, {}, closes_iso)
        msg = await ch.send(embed=em, view=BidPanelView())
        cid = await bidding_db.insert_cycle(guild_id, ty, tm, 'open', opens_iso, closes_iso, ch.id, msg.id)
        if cid is None:
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
            return
        await bidding_db.update_cycle_live_message(cid, ch.id, msg.id)

    async def _close_cycle(self, cycle: dict):
        cid = cycle['id']
        await bidding_db.update_cycle_phase(cid, 'closed')
        highs = await bidding_db.slot_high_bids(cid)
        ch_id = cycle.get('channel_id') or bidding_channel_id
        ch = self.bot.get_channel(ch_id) if ch_id else None
        if not ch or not isinstance(ch, discord.TextChannel):
            return

        lines = []
        for s in range(1, 11):
            if s in highs:
                cents, uid = highs[s]
                mem = ch.guild.get_member(uid)
                mention = mem.mention if mem else f'<@{uid}>'
                lines.append(f'SLOT {s} — {mention} (${cents / 100:.2f})')
            else:
                lines.append(f'SLOT {s} — *no bids*')

        em = discord.Embed(title=f'Slot bid winners ({cycle["target_year"]}-{cycle["target_month"]:02d})', description='\n'.join(lines), color=discord.Color.from_str(embed_color))
        wmsg = await ch.send(embed=em)
        await bidding_db.update_cycle_winners_message(cid, wmsg.id)

    async def _invoice_cycle(self, cycle: dict):
        cid = cycle['id']
        highs = await bidding_db.slot_high_bids(cid)
        fb = self.bot.get_channel(fallback_channel_id) if fallback_channel_id else None
        needed = [s for s in range(1, 11) if s in highs]

        if not stripe_invoices.stripe_configured():
            await bidding_db.update_cycle_phase(cid, 'invoiced')
            if fb and isinstance(fb, discord.TextChannel):
                await fb.send(f'Stripe is not configured; cycle **#{cid}** marked invoiced without payment links.')
            return

        if not needed:
            await bidding_db.update_cycle_phase(cid, 'invoiced')
            return

        for slot in needed:
            cents, uid = highs[slot]
            if await bidding_db.invoice_exists_for_slot(cid, slot):
                continue
            try:
                inv_id, url = await stripe_invoices.create_invoice_async(uid, cents, cid, slot, guild_id)
            except Exception as e:
                if fb and isinstance(fb, discord.TextChannel):
                    await fb.send(f'Stripe error cycle **#{cid}** slot **{slot}**: `{e!r}`')
                continue

            await bidding_db.insert_invoice_row(cid, slot, uid, cents, inv_id, 'pending')
            user = self.bot.get_user(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except discord.NotFound:
                    user = None
            if user:
                try:
                    await user.send(f'You won **slot {slot}** for **${cents / 100:.2f}**. Pay your invoice here: {url}')
                except discord.HTTPException:
                    if fb and isinstance(fb, discord.TextChannel):
                        await fb.send(f'Could not DM <@{uid}> for slot **{slot}** invoice. Link: {url}')
            elif fb and isinstance(fb, discord.TextChannel):
                await fb.send(f'User <@{uid}> not found for slot **{slot}** invoice. Link: {url}')

        missing = [
            s for s in needed if not await bidding_db.invoice_exists_for_slot(cid, s)
        ]
        if not missing:
            await bidding_db.update_cycle_phase(cid, 'invoiced')

async def setup(bot: commands.Bot):
    await bot.add_cog(BiddingSchedulerCog(bot), guilds=[discord.Object(id=guild_id)])