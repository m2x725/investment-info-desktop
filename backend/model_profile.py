"""Versioned local rate card. Provider invoices remain authoritative."""
from decimal import Decimal

PROFILE = {
    'model': 'kimi-k2.6', 'input_price': '6.5', 'output_price': '27',
    'cached_input_price': '1.1', 'prices_confirmed': True,
    'pricing_version': 'kimi-cn-2026-10-05',
    'pricing_source': 'https://platform.kimi.com/docs/pricing/chat',
}


def resolve_profile(values):
    result = dict(values)
    mode = result.get('pricing_mode', 'auto')
    if mode == 'auto':
        known = result.get('model', PROFILE['model']) == PROFILE['model']
        rates = (str(result.get('input_price', '0')), str(result.get('output_price', '0')))
        mode = 'builtin' if known and rates in (('0', '0'), ('6.5', '27'), ('6.50', '27.00')) else 'manual'
    result['pricing_mode'] = mode
    if mode == 'builtin':
        result.update(PROFILE)
    return result


def usage_cost(settings, usage):
    # Missing cache usage is conservatively estimated at the regular input rate.
    def count(value):
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError('Invalid token usage')
        return number
    prompt = count(usage['prompt_tokens'])
    completion = count(usage['completion_tokens'])
    cached = count(usage.get('cached_tokens', (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)))
    if cached > prompt:
        raise ValueError('Cached tokens exceed prompt tokens')
    cached_rate = settings.get('cached_input_price') if settings.get('pricing_mode') == 'builtin' else None
    return ((prompt-cached) * Decimal(str(settings['input_price'])) +
            cached * Decimal(str(cached_rate if cached_rate is not None else settings['input_price'])) +
            completion * Decimal(str(settings['output_price']))) / Decimal(1000000)
