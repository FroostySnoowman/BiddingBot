import asyncio
import stripe
import yaml

with open('config.yml', 'r') as file:
    _cfg = yaml.safe_load(file)

_stripe_section = _cfg.get('Stripe', {}) or {}
_stripe_key = _stripe_section.get('SECRET_KEY') or ''
_invoice_days = int(_stripe_section.get('INVOICE_DAYS_UNTIL_DUE', 7))

def _create_invoice_sync(user_id: int, amount_cents: int, cycle_id: int, slot: int, guild_id: int) -> tuple[str, str]:
    stripe.api_key = _stripe_key
    customer = stripe.Customer.create(metadata={'discord_user_id': str(user_id), 'guild_id': str(guild_id)})
    stripe.InvoiceItem.create(
        customer=customer.id,
        amount=amount_cents,
        currency='usd',
        description=f'Monthly slot {slot} winning bid (cycle #{cycle_id})',
    )
    inv = stripe.Invoice.create(
        customer=customer.id,
        collection_method='send_invoice',
        days_until_due=_invoice_days,
        metadata={
            'cycle_id': str(cycle_id),
            'slot': str(slot),
            'discord_user_id': str(user_id),
            'guild_id': str(guild_id),
        },
        auto_advance=False,
    )
    inv = stripe.Invoice.finalize_invoice(inv.id)
    url = inv.hosted_invoice_url or ''
    return inv.id, url

async def create_invoice_async(user_id: int, amount_cents: int, cycle_id: int, slot: int, guild_id: int) -> tuple[str, str]:
    return await asyncio.to_thread(_create_invoice_sync, user_id, amount_cents, cycle_id, slot, guild_id)

def stripe_configured() -> bool:
    return bool(_stripe_key)

def _invoice_is_paid_sync(stripe_invoice_id: str) -> bool:
    stripe.api_key = _stripe_key
    inv = stripe.Invoice.retrieve(stripe_invoice_id)
    return bool(inv['paid'])

async def invoice_is_paid_async(stripe_invoice_id: str) -> bool:
    return await asyncio.to_thread(_invoice_is_paid_sync, stripe_invoice_id)