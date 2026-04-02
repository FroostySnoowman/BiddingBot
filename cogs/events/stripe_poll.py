import discord
import yaml
from discord.ext import commands, tasks
from cogs.functions import bidding_db
from cogs.functions import stripe_invoices

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_invoice_log = int((_cfg.get('Channels', {}) or {}).get('INVOICE_LOG_CHANNEL_ID', 0) or 0)

class StripePollCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        if stripe_invoices.stripe_configured():
            self.poll_stripe_invoices.start()

    async def cog_unload(self):
        if self.poll_stripe_invoices.is_running():
            self.poll_stripe_invoices.cancel()

    @tasks.loop(minutes=2)
    async def poll_stripe_invoices(self):
        await self.bot.wait_until_ready()
        if not stripe_invoices.stripe_configured():
            return
        pending = await bidding_db.list_pending_invoices()
        if not pending:
            return
        log_ch = self.bot.get_channel(_invoice_log)
        for row in pending:
            inv_id = row['stripe_invoice_id']
            try:
                paid = await stripe_invoices.invoice_is_paid_async(inv_id)
            except Exception as e:
                print(f'[stripe_poll] retrieve {inv_id!r}: {e!r}')
                continue
            if not paid:
                continue
            updated = await bidding_db.mark_invoice_paid_if_pending(inv_id)
            if not updated:
                continue
            slot = row['slot']
            uid = row['user_id']
            dollars = row['amount_cents'] / 100
            if log_ch and isinstance(log_ch, discord.TextChannel):
                em = discord.Embed(
                    title='Invoice paid',
                    description=(
                        f'Slot **{slot}** — <@{uid}> paid **${dollars:.2f}** '
                        f'(Stripe invoice `{inv_id}`).'
                    ),
                    color=discord.Color.from_str(embed_color),
                )
                try:
                    await log_ch.send(embed=em)
                except discord.HTTPException:
                    pass

    @poll_stripe_invoices.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(StripePollCog(bot), guilds=[discord.Object(id=guild_id)])