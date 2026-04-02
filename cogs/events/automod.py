import collections
import discord
import yaml
import time
import re
from discord.ext import commands

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_am = _cfg.get('AutoMod', {}) or {}
_enabled = bool(_am.get('ENABLED', True))
_log_id = int(_am.get('LOG_CHANNEL_ID', 0) or 0)
_bypass = list(_am.get('BYPASS_ROLE_IDS', []) or [])
_block_invites = bool(_am.get('BLOCK_INVITES', True))
_blocked_words = [w.lower() for w in (_am.get('BLOCKED_WORDS', []) or []) if w]
_max_mentions = int(_am.get('MAX_MENTIONS', 8))
_flood_n = int(_am.get('FLOOD_MESSAGES', 5))
_flood_sec = float(_am.get('FLOOD_SECONDS', 7))
_caps_ratio = float(_am.get('MAX_CAPS_RATIO', 0.7))

_invite_re = re.compile(
    r'(discord\.gg/[\w-]+|discord(?:app)?\.com/invite/[\w-]+)',
    re.IGNORECASE,
)

class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._flood: dict[tuple[int, int], collections.deque] = collections.defaultdict(
            collections.deque
        )

    def _bypass(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_messages or member.guild_permissions.administrator:
            return True
        return any(r.id in _bypass for r in member.roles)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not _enabled:
            return
        if message.guild is None or message.guild.id != guild_id:
            return
        if message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return
        if self._bypass(message.author):
            return

        content = message.content or ''
        reason = None

        if _block_invites and _invite_re.search(content):
            reason = 'invite link'

        if reason is None and _blocked_words:
            low = content.lower()
            for w in _blocked_words:
                if w and w in low:
                    reason = 'blocked word'
                    break

        if reason is None:
            mention_count = len(message.mentions) + len(message.role_mentions)
            if mention_count > _max_mentions:
                reason = 'too many mentions'

        if reason is None and content:
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= 15:
                caps = sum(1 for c in letters if c.isupper())
                if caps / len(letters) >= _caps_ratio:
                    reason = 'excessive caps'

        if reason is None:
            key = (message.channel.id, message.author.id)
            now = time.monotonic()
            dq = self._flood[key]
            dq.append(now)
            while dq and now - dq[0] > _flood_sec:
                dq.popleft()
            if len(dq) >= _flood_n:
                reason = 'flood'

        if reason is None:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if _log_id:
            log_ch = self.bot.get_channel(_log_id)
            if log_ch and isinstance(log_ch, discord.TextChannel):
                em = discord.Embed(
                    title='AutoMod',
                    description=f'**{reason}** — deleted message from {message.author.mention} in {message.channel.mention}',
                    color=discord.Color.from_str(embed_color),
                )
                if len(content) <= 1000:
                    em.add_field(name='Content', value=content or '*(empty)*', inline=False)
                try:
                    await log_ch.send(embed=em)
                except discord.HTTPException:
                    pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCog(bot), guilds=[discord.Object(id=guild_id)])