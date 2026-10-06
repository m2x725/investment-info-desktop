"""Versioned local rate card. Provider invoices remain authoritative."""
from decimal import Decimal
import json
import re

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
    if mode == 'provider' and isinstance(result.get('provider_profile'), dict):
        result.update(result['provider_profile'])
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
    cached_rate = settings.get('cached_input_price') if settings.get('pricing_mode') in ('builtin','provider') else None
    return ((prompt-cached) * Decimal(str(settings['input_price'])) +
            cached * Decimal(str(cached_rate if cached_rate is not None else settings['input_price'])) +
            completion * Decimal(str(settings['output_price']))) / Decimal(1000000)


COMPATIBLE_MODELS = ('kimi-k2.6', 'kimi-k2.7-code', 'kimi-k2.7-code-highspeed')


def parse_official_rates(document):
    """Read numeric tables only; never execute remote MDX/JavaScript."""
    rates = {}
    for table in re.finditer(r'<DocTable\s+columns=\{(\[.*?\])\}\s+rows=\{(\[.*?\])\}\s*/>', document, re.S):
        columns = re.findall(r'title:\s*"([^"]+)"',table.group(1))
        rows = json.loads(re.sub(r',\s*([\]}])',r'\1',table.group(2)))
        for row in rows:
            if len(row)!=len(columns) or row[0] not in COMPATIBLE_MODELS or row[1]!='1M tokens':continue
            mapping=dict(zip(columns,row))
            def price(label):
                text=mapping[label]
                if not re.fullmatch(r'¥\d+(?:\.\d+)?',text):raise ValueError('Unsupported rate format')
                value=Decimal(text[1:])
                if value<0 or value>1000:raise ValueError('Invalid rate')
                return str(value)
            rates[row[0]]={'model':row[0], 'input_price':price('输入价格（缓存未命中）'),
                          'output_price':price('输出价格'),'cached_input_price':price('输入价格（缓存命中）'),
                          'prices_confirmed':True, 'pricing_source':PROFILE['pricing_source']}
    if not rates:raise ValueError('No compatible official rates')
    return rates


def select_api_profile(models, rates):
    available={m.get('id'):m for m in models if isinstance(m,dict)}
    for model in COMPATIBLE_MODELS:
        if model in available and model in rates:
            metadata=available[model]
            context=metadata.get('context_length')
            # Unknown context metadata is not replaced by a fabricated API value.
            return {**rates[model], 'context_length':context if isinstance(context,int) and context>0 else None,
                    'supports_reasoning':metadata.get('supports_reasoning'), 'configuration_source':'api_and_official_pricing'}
    raise ValueError('API returned no verified compatible research model')
