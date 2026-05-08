import discord
import html
import io
import yaml
import zipfile
from datetime import timezone
from cogs.functions import bidding_db

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_tickets = _cfg.get('Tickets', {}) or {}
_category_id = int(_tickets.get('TICKET_CATEGORY_ID', 0) or 0)
_staff_role_ids = list(_tickets.get('STAFF_ROLE_IDS', []) or [])
_categories = _tickets.get('CATEGORIES', {}) or {}
_transcript_channel_id = int(_tickets.get('TRANSCRIPT_CHANNEL_ID', 0) or 0)

def _staff_or_manage(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    return any(r.id in _staff_role_ids for r in member.roles)

def _build_html_transcript(ticket_name: str, ticket_type: str, opener: str, closer: str, messages: list[dict]) -> bytes:
    color = embed_color.lstrip('#')
    msg_rows = []
    for m in messages:
        ts = html.escape(m['ts'])
        author = html.escape(m['author'])
        uid = html.escape(str(m['uid']))
        body_parts = []
        if m['content']:
            body_parts.append(f'<p class="content">{html.escape(m["content"])}</p>')
        for em in m['embeds']:
            parts = []
            if em.get('title'):
                parts.append(f'<div class="em-title">{html.escape(em["title"])}</div>')
            if em.get('description'):
                parts.append(f'<div class="em-desc">{html.escape(em["description"])}</div>')
            if parts:
                body_parts.append(f'<div class="embed">{"".join(parts)}</div>')
        for att in m['attachments']:
            body_parts.append(f'<div class="attachment">📎 <a href="{html.escape(att)}" target="_blank">{html.escape(att)}</a></div>')
        body_html = '\n'.join(body_parts) or '<p class="content muted">[no content]</p>'
        msg_rows.append(f'''
        <div class="msg">
          <div class="meta">
            <span class="author">{author}</span>
            <span class="uid">({uid})</span>
            <span class="ts">{ts}</span>
          </div>
          <div class="body">{body_html}</div>
        </div>''')

    rows_html = '\n'.join(msg_rows)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Transcript – {html.escape(ticket_name)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #36393f; color: #dcddde; font-family: "Whitney", "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 14px; }}
  header {{ background: #2f3136; border-bottom: 2px solid #{color}; padding: 20px 28px; }}
  header h1 {{ font-size: 20px; color: #fff; margin-bottom: 8px; }}
  header .meta span {{ display: inline-block; margin-right: 20px; color: #b9bbbe; font-size: 13px; }}
  header .meta strong {{ color: #dcddde; }}
  .msgs {{ padding: 16px 28px; }}
  .msg {{ display: flex; flex-direction: column; padding: 6px 0; border-bottom: 1px solid #40444b; }}
  .msg:last-child {{ border-bottom: none; }}
  .meta {{ font-size: 12px; color: #72767d; margin-bottom: 3px; }}
  .author {{ font-weight: 700; color: #fff; font-size: 13px; margin-right: 4px; }}
  .uid {{ color: #72767d; margin-right: 6px; }}
  .ts {{ color: #72767d; }}
  .content {{ color: #dcddde; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
  .muted {{ color: #72767d; font-style: italic; }}
  .embed {{ border-left: 4px solid #{color}; background: #2f3136; padding: 8px 12px; margin-top: 4px; border-radius: 3px; }}
  .em-title {{ font-weight: 700; color: #fff; margin-bottom: 3px; }}
  .em-desc {{ color: #dcddde; white-space: pre-wrap; font-size: 13px; }}
  .attachment {{ font-size: 12px; color: #00b0f4; margin-top: 4px; }}
  .attachment a {{ color: inherit; }}
</style>
</head>
<body>
<header>
  <h1>#{html.escape(ticket_name)}</h1>
  <div class="meta">
    <span><strong>Type:</strong> {html.escape(ticket_type)}</span>
    <span><strong>Opened by:</strong> {html.escape(opener)}</span>
    <span><strong>Closed by:</strong> {html.escape(closer)}</span>
    <span><strong>Messages:</strong> {len(messages)}</span>
  </div>
</header>
<div class="msgs">
{rows_html}
</div>
</body>
</html>'''.encode('utf-8')

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

    topic = f'opener_id:{interaction.user.id}|type:{key}'
    ch = await guild.create_text_channel(name=name, category=parent, overwrites=overwrites, topic=topic)
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
        if not isinstance(ch, discord.TextChannel):
            return

        # parse opener + type from channel topic
        opener_id = None
        ticket_type = 'unknown'
        if ch.topic:
            for part in ch.topic.split('|'):
                if part.startswith('opener_id:'):
                    try:
                        opener_id = int(part.split(':', 1)[1])
                    except ValueError:
                        pass
                elif part.startswith('type:'):
                    ticket_type = part.split(':', 1)[1]

        opener_user = interaction.guild.get_member(opener_id) if (opener_id and interaction.guild) else None
        opener_str = f'{opener_user} ({opener_id})' if opener_user else (str(opener_id) if opener_id else 'Unknown')
        closer_str = f'{interaction.user} ({interaction.user.id})'
        closed_at = discord.utils.utcnow()

        transcript_ch = interaction.guild and interaction.guild.get_channel(_transcript_channel_id)
        if isinstance(transcript_ch, discord.TextChannel):
            messages = []
            async for msg in ch.history(limit=None, oldest_first=True):
                messages.append({
                    'ts': msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'author': str(msg.author),
                    'uid': msg.author.id,
                    'content': msg.content or '',
                    'embeds': [
                        {'title': e.title or '', 'description': e.description or ''}
                        for e in msg.embeds
                    ],
                    'attachments': [a.url for a in msg.attachments],
                })

            # pull the modal answers from the first message's embed description
            ticket_description = None
            if messages:
                first_embeds = messages[0]['embeds']
                if first_embeds and first_embeds[0].get('description'):
                    ticket_description = first_embeds[0]['description']

            html_bytes = _build_html_transcript(ch.name, ticket_type, opener_str, closer_str, messages)
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f'transcript-{ch.name}.html', html_bytes)
            zip_buf.seek(0)
            html_file = discord.File(zip_buf, filename=f'transcript-{ch.name}.zip')

            em = discord.Embed(
                title=f'Ticket closed — #{ch.name}',
                description=ticket_description or '',
                color=discord.Color.from_str(embed_color),
                timestamp=closed_at,
            )
            em.add_field(name='Opened by', value=opener_user.mention if opener_user else opener_str, inline=True)
            em.add_field(name='Closed by', value=interaction.user.mention, inline=True)
            em.set_footer(text='Transcript attached')

            await transcript_ch.send(embed=em, file=html_file)

        try:
            await ch.delete()
        except discord.HTTPException:
            pass
