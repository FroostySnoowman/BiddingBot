import discord
import yaml
from discord.ext import commands

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_welcome_channel_id = int(_cfg.get('Welcome', {}).get('CHANNEL_ID', 0) or 0)

class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != guild_id:
            return
        if not _welcome_channel_id:
            return
        ch = member.guild.get_channel(_welcome_channel_id)
        if not isinstance(ch, discord.TextChannel):
            return

        em = discord.Embed(title='Welcome to SMPFinder!', description=f'Hey {member.mention}, glad to have you here!\n\n**SMPFinder** is the home of [smpfinder.com](https://smpfinder.com) — the official platform for discovering and joining Minecraft SMPs.\n\n> If you have any questions or need help, open a ticket in <#1494137036360257627>.\n\nEnjoy your stay and we hope you find the perfect SMP!', color=discord.Color.from_str(embed_color))
        em.set_thumbnail(url=member.display_avatar.url)
        if member.guild.banner:
            em.set_image(url=member.guild.banner.url)
        em.set_footer(text=f'You are member #{member.guild.member_count} • SMPFinder')
        await ch.send(embed=em)

async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))