import asyncio
import discord
import html
import io
import yaml
import zipfile
from cogs.functions import bidding_db
from cogs.functions.dm_footer import SMPFINDER_PROMO

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

guild_id = _cfg['General']['GUILD_ID']
embed_color = _cfg['General']['EMBED_COLOR']
_tickets = _cfg.get('Tickets', {}) or {}
_category_id = int(_tickets.get('TICKET_CATEGORY_ID', 0) or 0)
_staff_role_ids = list(_tickets.get('STAFF_ROLE_IDS', []) or [])
_categories = _tickets.get('CATEGORIES', {}) or {}
_transcript_channel_id = int(_tickets.get('TRANSCRIPT_CHANNEL_ID', 0) or 0)
_announce_channel_id = int(_tickets.get('PARTNERSHIP_ANNOUNCE_CHANNEL_ID', 0) or 0)
_partnership_forum_tag_ids: list[int] = []
for _tid in _tickets.get('PARTNERSHIP_FORUM_TAG_IDS', []) or []:
    try:
        _partnership_forum_tag_ids.append(int(_tid))
    except (TypeError, ValueError):
        pass

_FIELD_SERVER_NAME = '🏰 Server Name'
_FIELD_ADVERTISEMENT = '💬 Advertisement'
_FIELD_DISCORD_INVITE = '🔗 Discord Invite'
_LOGO_FILENAME = 'partnership_logo.png'

_PARTNERSHIP_EVIDENCE_PROMPT = (
    'Please send our AD with an @everyone ping and attach a FULL screenshot of evidence that you sent our AD.\n'
    'Copy of our AD below:\n\n'
    '**MASSIVE $100 USD GIVEAWAY**\n'
    'JOIN THE SERVER AND PARTNER TO WIN\n'
    'SMP Finder is a MC community and Minecraft server list.\n'
    '💰$100 PRIZE!!!\n'
    '🔗 https://www.smpfinder.com\n'
    '👑 https://discord.gg/findsmp | @everyone'
)

PARTNERSHIP_QA_STEPS: list[tuple[str, str, bool]] = [
    ('advertisement', 'Please provide your full advertisement without any links and only use normal emojis!', False),
    ('server_name', 'What is your server name?', False),
    ('evidence', _PARTNERSHIP_EVIDENCE_PROMPT, True),
    ('logo', 'Can you provide the logo to your server?', True),
    ('visibility', 'Is your server public or private?', False),
    ('listed', 'Is your server listed on our free website https://www.smpfinder.com', False),
]

APPLY_QA_STEPS: list[tuple[str, str, bool]] = [
    ('age_region_timezone', "What's your current age, region, and timezone?", False),
    ('good_fit', 'Why would you be a good fit for the staff team?', False),
    ('skills', 'What skills do you bring to the staff team?', False),
    ('why_staff', 'Why do you want to be a staff member?', False),
    ('staff_positions', 'Please share your current and previous staffing positions', False),
    ('friend_rule_break', 'If you saw a friend breaking a rule, how would you handle this?', False),
    ('owners_arguing', 'If you saw two server owners arguing in general, how would you handle this?', False),
    ('staff_rule_break', 'What would you do if a fellow staff member were breaking staff rules or server rules?', False),
    ('activity', 'We require staff to be active. Can you do that?', False),
    ('anything_else', "Is there anything else you'd like to add?", False),
]

def _staff_or_manage(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    return any(r.id in _staff_role_ids for r in member.roles)

def _truncate(s: str, max_len: int = 1024) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'

def _message_has_illegal_ping(message: discord.Message) -> bool:
    if message.mention_everyone:
        return True
    content = (message.content or '').lower()
    if '@everyone' in content or '@here' in content:
        return True
    return False

async def _close_and_transcript(bot: discord.Client, ch: discord.TextChannel, closer: discord.Member):
    guild = ch.guild
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

    opener_user = guild.get_member(opener_id) if opener_id else None
    opener_str = f'{opener_user} ({opener_id})' if opener_user else (str(opener_id) if opener_id else 'Unknown')
    closer_str = f'{closer} ({closer.id})'
    closed_at = discord.utils.utcnow()

    transcript_ch = guild.get_channel(_transcript_channel_id)
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

        em = discord.Embed(title=f'Ticket closed — #{ch.name}', description=ticket_description or '', color=discord.Color.from_str(embed_color), timestamp=closed_at)
        em.add_field(name='Opened by', value=opener_user.mention if opener_user else opener_str, inline=True)
        em.add_field(name='Closed by', value=closer.mention, inline=True)
        em.set_footer(text='Transcript attached')

        try:
            await transcript_ch.send(embed=em, file=html_file)
        except discord.HTTPException:
            pass

    try:
        await ch.delete()
    except discord.HTTPException:
        pass

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

def _embed_field_value(embed: discord.Embed, field_name: str) -> str | None:
    for f in embed.fields:
        if f.name == field_name:
            v = (f.value or '').strip()
            return v if v else None
    return None

def _resolve_forum_applied_tags(forum: discord.ForumChannel) -> list[discord.ForumTag]:
    out: list[discord.ForumTag] = []
    for tid in _partnership_forum_tag_ids:
        t = forum.get_tag(tid)
        if t is not None:
            out.append(t)
    return out

async def _create_partnership_forum_post(
    forum: discord.ForumChannel,
    review_embed: discord.Embed,
    review_msg: discord.Message,
):
    server_name = _embed_field_value(review_embed, _FIELD_SERVER_NAME) or 'Partnership'
    advertisement = _embed_field_value(review_embed, _FIELD_ADVERTISEMENT) or ''
    invite = _embed_field_value(review_embed, _FIELD_DISCORD_INVITE) or ''

    thread_name = server_name[:100]
    text_body = _truncate(advertisement, 4096)
    welcome_title = _truncate(f'Welcome to {server_name}', 256)

    content = f'{server_name}\n\nSMP Finder: {server_name}'

    pub = discord.Embed(
        title=welcome_title,
        description=text_body,
        color=discord.Color.from_str(embed_color),
        timestamp=discord.utils.utcnow(),
    )
    if invite:
        pub.add_field(name='🔗 Discord Invite', value=_truncate(invite, 1024), inline=False)

    kwargs: dict = {
        'name': thread_name,
        'content': content,
        'embed': pub,
    }

    files: list[discord.File] = []
    if review_msg.attachments:
        logo_att = review_msg.attachments[-1]
        try:
            data = await logo_att.read()
        except discord.HTTPException:
            data = None
        if data:
            files.append(discord.File(io.BytesIO(data), filename=_LOGO_FILENAME))
            pub.set_image(url=f'attachment://{_LOGO_FILENAME}')

    if files:
        kwargs['files'] = files

    applied = _resolve_forum_applied_tags(forum)
    if applied:
        kwargs['applied_tags'] = applied

    return await forum.create_thread(**kwargs)

def _copy_embed_from_src(src: discord.Embed) -> discord.Embed:
    out = discord.Embed(title=src.title, description=src.description, color=src.color)
    if src.url:
        out.url = src.url
    if src.timestamp:
        out.timestamp = src.timestamp
    if getattr(src.footer, 'text', None):
        kw: dict = {'text': src.footer.text}
        if src.footer.icon_url:
            kw['icon_url'] = src.footer.icon_url
        out.set_footer(**kw)
    for field in src.fields:
        out.add_field(name=field.name, value=field.value, inline=field.inline)
    if src.image and src.image.url:
        out.set_image(url=src.image.url)
    if src.thumbnail and src.thumbnail.url:
        out.set_thumbnail(url=src.thumbnail.url)
    return out

class PartnershipReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Accept', style=discord.ButtonStyle.success, custom_id='partnership_review_accept')
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _staff_or_manage(interaction.user):
            await interaction.response.send_message('Only staff can use this.', ephemeral=True)
            return
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message('Invalid channel.', ephemeral=True)
            return
        msg = interaction.message
        if msg is None or not msg.embeds:
            await interaction.response.send_message('Missing embed.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not _announce_channel_id:
            await interaction.followup.send('Set PARTNERSHIP_ANNOUNCE_CHANNEL_ID in config.yml before approving.', ephemeral=True)
            return

        announce_ch = ch.guild.get_channel(_announce_channel_id)
        if announce_ch is None:
            await interaction.followup.send('Partnership announcement channel not found.', ephemeral=True)
            return

        opener_id = None
        if ch.topic:
            for part in ch.topic.split('|'):
                if part.startswith('opener_id:'):
                    try:
                        opener_id = int(part.split(':', 1)[1])
                    except ValueError:
                        pass

        target = ch.guild.get_member(opener_id) if (opener_id and ch.guild) else None
        if target is None and opener_id:
            try:
                target = await interaction.client.fetch_user(opener_id)
            except discord.NotFound:
                target = None

        try:
            if isinstance(announce_ch, discord.ForumChannel):
                twm = await _create_partnership_forum_post(announce_ch, msg.embeds[0], msg)
                jump_url = twm.thread.jump_url
            elif isinstance(announce_ch, discord.TextChannel):
                embed_copy = _copy_embed_from_src(msg.embeds[0])
                new_files: list[discord.File] = []
                for att in msg.attachments:
                    try:
                        data = await att.read()
                        new_files.append(discord.File(io.BytesIO(data), filename=att.filename))
                    except discord.HTTPException:
                        pass
                posted = await announce_ch.send(embed=embed_copy, files=new_files[:10])
                jump_url = posted.jump_url
            else:
                await interaction.followup.send(
                    'Partnership announcement channel must be a forum channel or a text channel.',
                    ephemeral=True,
                )
                return
        except discord.HTTPException:
            await interaction.followup.send('Could not post to the partnership announcement channel.', ephemeral=True)
            return

        dm_ok = False
        if target is not None:
            try:
                await target.send(
                    f'Your partnership application has been approved! You can view the approved post here: {jump_url}'
                    f'{SMPFINDER_PROMO}'
                )
                dm_ok = True
            except discord.Forbidden:
                pass

        await _close_and_transcript(interaction.client, ch, interaction.user)

        if dm_ok:
            await interaction.followup.send('Partnership approved, posted, and ticket closed.', ephemeral=True)
        elif target is None:
            await interaction.followup.send('Posted and ticket closed, but the opener could not be found to send a DM.', ephemeral=True)
        else:
            await interaction.followup.send('Posted and ticket closed, but could not DM the user (DMs may be closed).', ephemeral=True)

    @discord.ui.button(label='Deny', style=discord.ButtonStyle.danger, custom_id='partnership_review_deny')
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _staff_or_manage(interaction.user):
            await interaction.response.send_message('Only staff can use this.', ephemeral=True)
            return
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message('Invalid channel.', ephemeral=True)
            return

        staff_id = interaction.user.id
        await interaction.response.send_message('Reply in this channel with the denial reason.', ephemeral=True)
        await ch.send(f'{interaction.user.mention} please type the reason for denial.')

        try:
            reason_msg = await interaction.client.wait_for('message', timeout=600.0, check=lambda m, c=ch, s=staff_id: m.channel.id == c.id and m.author.id == s and not m.author.bot)
        except asyncio.TimeoutError:
            await ch.send('Denial reason timed out. Use Deny again or Close the ticket.')
            return

        reason = (reason_msg.content or '').strip() or 'No reason provided.'

        opener_id = None
        if ch.topic:
            for part in ch.topic.split('|'):
                if part.startswith('opener_id:'):
                    try:
                        opener_id = int(part.split(':', 1)[1])
                    except ValueError:
                        pass

        target = ch.guild.get_member(opener_id) if (opener_id and ch.guild) else None
        if target is None and opener_id:
            try:
                target = await interaction.client.fetch_user(opener_id)
            except discord.NotFound:
                target = None

        if target is not None:
            try:
                await target.send(f'Your partnership application was denied.\nReason: {reason}{SMPFINDER_PROMO}')
            except discord.Forbidden:
                pass

        await _close_and_transcript(interaction.client, ch, interaction.user)

async def _ask_partner_step(bot: discord.Client, channel: discord.TextChannel, opener: discord.abc.User, prompt: str, collect_attachments: bool) -> dict | None:
    mention_target = opener
    if channel.guild:
        mention_target = channel.guild.get_member(opener.id) or opener
    allowed = discord.AllowedMentions(everyone=False, roles=False, users=[mention_target] if mention_target else [])

    while True:
        await channel.send(f'{mention_target.mention} {prompt}', allowed_mentions=allowed)
        try:
            msg = await bot.wait_for('message', timeout=1800.0, check=lambda m, c=channel, uid=opener.id: m.channel.id == c.id and m.author.id == uid and not m.author.bot)
        except asyncio.TimeoutError:
            await channel.send('Question timed out — staff can close this ticket.')
            return None

        if _message_has_illegal_ping(msg):
            await channel.send('Please include no pings in your message, respond to the previous question again.',)
            continue

        text = (msg.content or '').strip()
        files: list[tuple[str, bytes]] = []
        if collect_attachments and msg.attachments:
            for att in msg.attachments:
                try:
                    data = await att.read()
                    files.append((att.filename or 'attachment', data))
                except (discord.HTTPException, OSError):
                    pass

        return {'text': text, 'files': files}

async def _run_partnership_qa(bot: discord.Client, channel: discord.TextChannel, opener: discord.abc.User, modal_values: dict[str, str]):
    answers: dict[str, object] = {}
    for key, prompt, want_files in PARTNERSHIP_QA_STEPS:
        step = await _ask_partner_step(bot, channel, opener, prompt, want_files)
        if step is None:
            return
        if want_files:
            answers[key] = step
        else:
            answers[key] = step['text']

    mem = channel.guild.get_member(opener.id) if channel.guild else None
    applicant_val = mem.mention if mem else f'<@{opener.id}>'

    ev = answers['evidence']  # type: ignore
    lo = answers['logo']  # type: ignore
    assert isinstance(ev, dict) and isinstance(lo, dict)

    ev_text = _truncate((ev.get('text') or '') or '\u200b')
    lo_text = _truncate((lo.get('text') or '') or '\u200b')

    em = discord.Embed(title='Complete Partnership Submission', color=discord.Color.from_str(embed_color))
    em.add_field(name='👤 Applicant', value=applicant_val, inline=False)
    em.add_field(name='🏰 Server Name', value=_truncate(str(answers['server_name'])), inline=False)
    em.add_field(name='👑 Ownership', value=_truncate(modal_values['ownership']), inline=False)
    em.add_field(name='🤝 Previous Partner', value=_truncate(modal_values['prev_partner']), inline=False)
    em.add_field(name='🛒 Store', value=_truncate(modal_values['store']), inline=False)
    em.add_field(name='🔗 Discord Invite', value=_truncate(modal_values['discord_invite']), inline=False)
    em.add_field(name='💬 Advertisement', value=_truncate(str(answers['advertisement'])), inline=False)
    em.add_field(name='📸 Evidence', value=ev_text, inline=False)
    em.add_field(name='🖌️ Logo', value=lo_text, inline=False)
    em.add_field(name='🔒 Visibility', value=_truncate(str(answers['visibility'])), inline=False)
    em.add_field(name='🌐 Listed on smpfinder', value=_truncate(str(answers['listed'])), inline=False)

    review_files: list[discord.File] = []
    for name, data in ev.get('files', []):
        review_files.append(discord.File(io.BytesIO(data), filename=name))
    for name, data in lo.get('files', []):
        review_files.append(discord.File(io.BytesIO(data), filename=name))

    await channel.send(embed=em, view=PartnershipReviewView(), files=review_files[:10])

async def _run_apply_qa(bot: discord.Client, channel: discord.TextChannel, opener: discord.abc.User):
    answers: dict[str, str] = {}
    for key, prompt, want_files in APPLY_QA_STEPS:
        step = await _ask_partner_step(bot, channel, opener, prompt, want_files)
        if step is None:
            return
        answers[key] = step['text']

    mem = channel.guild.get_member(opener.id) if channel.guild else None
    applicant_val = mem.mention if mem else f'<@{opener.id}>'

    em = discord.Embed(title='Complete Staff Application', color=discord.Color.from_str(embed_color))
    em.add_field(name='👤 Applicant', value=applicant_val, inline=False)
    em.add_field(name='🎂 Age, region & timezone', value=_truncate(answers['age_region_timezone']), inline=False)
    em.add_field(name='✅ Good fit', value=_truncate(answers['good_fit']), inline=False)
    em.add_field(name='🛠️ Skills', value=_truncate(answers['skills']), inline=False)
    em.add_field(name='💼 Why staff', value=_truncate(answers['why_staff']), inline=False)
    em.add_field(name='📋 Staffing positions', value=_truncate(answers['staff_positions']), inline=False)
    em.add_field(name='👥 Friend breaking rules', value=_truncate(answers['friend_rule_break']), inline=False)
    em.add_field(name='⚔️ Owners arguing', value=_truncate(answers['owners_arguing']), inline=False)
    em.add_field(name='🛡️ Fellow staff breaking rules', value=_truncate(answers['staff_rule_break']), inline=False)
    em.add_field(name='📅 Activity', value=_truncate(answers['activity']), inline=False)
    em.add_field(name='📝 Anything else', value=_truncate(answers['anything_else']), inline=False)

    await channel.send(embed=em)

async def _open_apply_ticket(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send('Wrong server.', ephemeral=True)
        return

    num = await bidding_db.next_ticket_number()
    name = f'apply-{num}'

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

    topic = f'opener_id:{interaction.user.id}|type:apply'
    ch = await guild.create_text_channel(name=name, category=parent, overwrites=overwrites, topic=topic)
    pings = ' '.join(f'<@&{rid}>' for rid in _staff_role_ids)
    header = f'{interaction.user.mention} {pings}'.strip()

    info = discord.Embed(
        title=_categories.get('apply', 'Apply'),
        description='Staff application — answer the bot questions below.',
        color=discord.Color.from_str(embed_color),
    )
    info.add_field(name='👤 Applicant', value=interaction.user.mention, inline=False)
    info.set_footer(text='Staff can close with the lock button.')

    v = TicketCloseView()
    await ch.send(content=header, embed=info, view=v)
    await interaction.followup.send(f'Ticket created: {ch.mention}', ephemeral=True)

    asyncio.create_task(_run_apply_qa(interaction.client, ch, interaction.user))

async def _open_partnership_ticket(interaction: discord.Interaction, modal_values: dict[str, str]):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send('Wrong server.', ephemeral=True)
        return

    num = await bidding_db.next_ticket_number()
    name = f'partnership-{num}'

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

    topic = f'opener_id:{interaction.user.id}|type:partner'
    ch = await guild.create_text_channel(name=name, category=parent, overwrites=overwrites, topic=topic)
    pings = ' '.join(f'<@&{rid}>' for rid in _staff_role_ids)
    header = f'{interaction.user.mention} {pings}'.strip()

    info = discord.Embed(title='Partnership Application Info', color=discord.Color.from_str(embed_color))
    info.add_field(name='👤 Applicant', value=interaction.user.mention, inline=False)
    info.add_field(name='👑 Ownership', value=modal_values['ownership'], inline=False)
    info.add_field(name='🤝 Previous Partner', value=modal_values['prev_partner'], inline=False)
    info.add_field(name='🛒 Store', value=modal_values['store'], inline=False)
    info.add_field(name='🔗 Discord Invite', value=modal_values['discord_invite'], inline=False)
    info.set_footer(text='Staff can close with the lock button. Answer the bot questions below.')

    v = TicketCloseView()
    await ch.send(content=header, embed=info, view=v)
    await interaction.followup.send(f'Ticket created: {ch.mention}', ephemeral=True)

    asyncio.create_task(_run_partnership_qa(interaction.client, ch, interaction.user, dict(modal_values)))

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

class PartnerModal(discord.ui.Modal, title='Partner'):
    ownership = discord.ui.TextInput(
        label='Do you own the server? (Yes/No)',
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    prev_partner = discord.ui.TextInput(
        label='Previous partner? (Yes/No)',
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    store = discord.ui.TextInput(
        label='Store link (N/A if none)',
        style=discord.TextStyle.short,
        required=True,
        max_length=500,
    )
    discord_invite = discord.ui.TextInput(
        label='Discord invite link',
        style=discord.TextStyle.short,
        required=True,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        modal_values = {
            'ownership': self.ownership.value.strip(),
            'prev_partner': self.prev_partner.value.strip(),
            'store': self.store.value.strip(),
            'discord_invite': self.discord_invite.value.strip(),
        }
        await _open_partnership_ticket(interaction, modal_values)

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for item in self.children:
            if getattr(item, 'custom_id', None) == 'ticket_panel_partner':
                item.label = str(_categories.get('partner', 'Partner'))
                break

    @discord.ui.button(label='Apply', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_apply')
    async def btn_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _open_apply_ticket(interaction)

    @discord.ui.button(label='Support', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_support')
    async def btn_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SupportModal())

    @discord.ui.button(label='Bugs', style=discord.ButtonStyle.blurple, custom_id='ticket_panel_bugs')
    async def btn_bugs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BugsModal())

    @discord.ui.button(label='General', style=discord.ButtonStyle.grey, custom_id='ticket_panel_general')
    async def btn_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GeneralModal())

    @discord.ui.button(label='Partner', style=discord.ButtonStyle.success, custom_id='ticket_panel_partner', row=1)
    async def btn_partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PartnerModal())

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

        await _close_and_transcript(interaction.client, ch, interaction.user)