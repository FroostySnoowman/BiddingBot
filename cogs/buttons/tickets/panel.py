import discord
import yaml
from cogs.functions import bidding_db

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_tickets = _cfg.get('Tickets', {}) or {}
_category_id = int(_tickets.get('TICKET_CATEGORY_ID', 0) or 0)
_staff_role_ids = list(_tickets.get('STAFF_ROLE_IDS', []) or [])
_categories = _tickets.get('CATEGORIES', {}) or {}

def _staff_or_manage(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    return any(r.id in _staff_role_ids for r in member.roles)

async def _open_ticket(interaction: discord.Interaction, key: str, title: str, body_lines: list[str]):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send('Wrong server.', ephemeral=True)
        return

    num = await bidding_db.next_ticket_number()
    slug = key[:12].replace(' ', '-')
    name = f'{slug}-{num}'

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    for rid in _staff_role_ids:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

    parent = guild.get_channel(_category_id)
    if not isinstance(parent, discord.CategoryChannel):
        await interaction.followup.send('Ticket category not configured.', ephemeral=True)
        return

    ch = await guild.create_text_channel(name=name, category=parent, overwrites=overwrites)
    pings = ' '.join(f'<@&{rid}>' for rid in _staff_role_ids)
    header = f'{interaction.user.mention} {pings}'.strip()

    em = discord.Embed(title=title, description='\n'.join(body_lines), color=discord.Color.from_str(embed_color))
    em.set_footer(text='Staff can close with the lock button.')
    v = TicketCloseView()
    await ch.send(content=header, embed=em, view=v)
    await interaction.followup.send(f'Ticket created: {ch.mention}', ephemeral=True)

class ApplyModal(discord.ui.Modal, title='Apply'):
    q1 = discord.ui.TextInput(
        label='Why do you want to join?',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )
    q2 = discord.ui.TextInput(
        label='Relevant experience / links',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _open_ticket(
            interaction,
            'apply',
            _categories.get('apply', 'Apply'),
            [
                f'**Why apply:** {self.q1.value}',
                f'**Experience:** {self.q2.value}',
            ],
        )

class SupportModal(discord.ui.Modal, title='Support'):
    q1 = discord.ui.TextInput(
        label='What do you need help with?',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )
    q2 = discord.ui.TextInput(
        label='Details / steps tried',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _open_ticket(
            interaction,
            'support',
            _categories.get('support', 'Support'),
            [
                f'**Issue:** {self.q1.value}',
                f'**Details:** {self.q2.value}',
            ],
        )

class BugsModal(discord.ui.Modal, title='Bugs'):
    q1 = discord.ui.TextInput(
        label='What happened?',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )
    q2 = discord.ui.TextInput(
        label='Expected vs actual / reproduce steps',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _open_ticket(
            interaction,
            'bugs',
            _categories.get('bugs', 'Bugs'),
            [
                f'**What happened:** {self.q1.value}',
                f'**Expected / steps:** {self.q2.value}',
            ],
        )

class GeneralModal(discord.ui.Modal, title='General'):
    q1 = discord.ui.TextInput(
        label='Topic',
        required=True,
        max_length=200,
    )
    q2 = discord.ui.TextInput(
        label='Message',
        style=discord.TextStyle.long,
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _open_ticket(
            interaction,
            'general',
            _categories.get('general', 'General'),
            [
                f'**Topic:** {self.q1.value}',
                f'**Message:** {self.q2.value}',
            ],
        )

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Apply', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_apply')
    async def btn_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyModal())

    @discord.ui.button(label='Support', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_support')
    async def btn_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SupportModal())

    @discord.ui.button(label='Bugs', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_bugs')
    async def btn_bugs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BugsModal())

    @discord.ui.button(label='General', style=discord.ButtonStyle.grey, custom_id='ticket_panel_general')
    async def btn_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GeneralModal())

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji='🔒', label='Close', style=discord.ButtonStyle.danger, custom_id='ticket_close_lock')
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _staff_or_manage(interaction.user):
            await interaction.response.send_message('Only staff can close this ticket.', ephemeral=True)
            return

        ch = interaction.channel
        await interaction.response.send_message('Closing…', ephemeral=True)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.delete()
            except discord.HTTPException:
                pass