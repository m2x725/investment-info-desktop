from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from urllib.parse import urlparse
import re
from pydantic import BaseModel, Field, field_validator, model_validator


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("数字必须是有限值")
    return result


def money(value):
    return str(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Security(BaseModel):
    exchange: Literal["SH", "SZ", "BJ", "HK"]
    ticker: str = Field(min_length=1, max_length=6)
    name: str = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def check_code(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("请填写公司名称")
        if self.exchange == "HK":
            if not re.fullmatch(r"\d{1,5}", self.ticker):
                raise ValueError("港股代码应为 1 至 5 位数字")
            self.ticker = self.ticker.zfill(5)
        elif not re.fullmatch(r"\d{6}", self.ticker):
            raise ValueError("A股代码应为 6 位数字")
        return self


class Position(Security):
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"), decimal_places=6)
    cost: Decimal = Field(ge=-Decimal("10000000"), le=Decimal("10000000"), decimal_places=6)
    note: str = Field(default="", max_length=300)


class Cash(BaseModel):
    currency: Literal["CNY", "HKD"]
    amount: Decimal = Field(ge=0, le=Decimal("1000000000000"), decimal_places=2)


class ManualQuote(BaseModel):
    price: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=6)
    previous: Decimal | None = Field(default=None, gt=0, le=Decimal("10000000"))
    as_of: date
    source: str = Field(min_length=2, max_length=200)

    @field_validator("as_of")
    @classmethod
    def not_future(cls, value):
        if value > (datetime.now(timezone.utc) + timedelta(hours=8)).date():
            raise ValueError("日期不能晚于北京时间今天")
        return value


class Fx(BaseModel):
    rate: Decimal = Field(gt=0, le=100)
    as_of: date
    source: str = Field(min_length=2, max_length=200)

    _date_check = field_validator("as_of")(ManualQuote.not_future.__func__)


class Evidence(BaseModel):
    security_id: str
    title: str = Field(min_length=2, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    published_at: date
    report_period: str = Field(default="", max_length=60)
    locator: str = Field(default="", max_length=100)
    content: str = Field(min_length=20, max_length=80000)
    kind: Literal["financial", "announcement", "news"] = "financial"

    @field_validator("url")
    @classmethod
    def public_link(cls, value):
        u = urlparse(value)
        if u.scheme != "https" or not u.hostname or u.username or u.password:
            raise ValueError("来源必须是公开 HTTPS 链接")
        return value

    _date_check = field_validator("published_at")(ManualQuote.not_future.__func__)


class Settings(BaseModel):
    model_config = {"validate_default": True}
    pricing_mode: Literal["auto", "builtin", "manual"] = "auto"
    cached_input_price: Decimal | None = Field(default=None, ge=0, le=1000)
    pricing_version: str = ""
    pricing_source: str = ""
    model: str = Field(default="kimi-k2.6", pattern=r"^kimi-[a-zA-Z0-9.-]+$")
    monthly_limit: Decimal = Field(default=200, gt=0, le=200)
    other_service_cost: Decimal = Field(default=0, ge=0, le=200, decimal_places=2)
    input_price: Decimal = Field(default=0, ge=0, le=1000)
    output_price: Decimal = Field(default=0, ge=0, le=1000)
    prices_confirmed: bool = False
    daily_time: str = Field(default="08:00", pattern=r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$")
    daily_times: list[str] | None = None
    scheduler_enabled: bool = True
    scheduler_paused: bool = False
    push_enabled: bool = False
    auto_research: bool = False
    event_research: bool = False
    concentration: Decimal = Field(default=15, gt=0, le=100)
    move_threshold: Decimal = Field(default=5, gt=0, le=100)
    import_folder: str = Field(default="", max_length=1000)
    online_research: bool = True
    quote_provider: Literal["public","futu"] = "public"
    weekly_research_limit: int = Field(default=2, ge=1, le=10)

    @model_validator(mode="before")
    @classmethod
    def built_in_model(cls, values):
        from .model_profile import resolve_profile
        if isinstance(values, dict):return resolve_profile(values)
        return values

    @field_validator('daily_times')
    @classmethod
    def valid_daily_times(cls, values):
        if values is None:return None
        if not values:raise ValueError('请至少设置一个简报时间')
        if any(not re.fullmatch(r'(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]', v) for v in values):
            raise ValueError('简报时间须为00:00至23:59')
        return sorted(set(values))

    @model_validator(mode="after")
    def confirmed_prices(self):
        if self.other_service_cost > self.monthly_limit:
            raise ValueError("其他服务费用不能超过月度总上限")
        if self.prices_confirmed and (self.input_price <= 0 or self.output_price <= 0):
            raise ValueError("确认价格前，请填写大于零的输入和输出单价")
        return self


class Secrets(BaseModel):
    kimi_key: str = Field(default="", max_length=300)
    push_key: str = Field(default="", max_length=300)
    clear_kimi: bool = False
    clear_push: bool = False


class ResearchRequest(BaseModel):
    security_id: str
    question: str = Field(default="业务、最新变化、估值与继续持有的风险", max_length=300)


class Followup(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class ValuationInput(BaseModel):
    evidence_id: int = Field(gt=0)
    currency: Literal["CNY", "HKD"]
    earnings_basis: Literal["annual", "ttm"]
    report_period: str = Field(min_length=4, max_length=60)
    as_of: date
    eps: Decimal | None = Field(default=None, ge=-1000000, le=1000000, decimal_places=6)
    book_per_share: Decimal | None = Field(default=None, ge=-1000000, le=1000000, decimal_places=6)
    dividend_per_share: Decimal | None = Field(default=None, ge=0, le=1000000, decimal_places=6)
    locator: str = Field(min_length=2, max_length=100)
    _date_check = field_validator("as_of")(ManualQuote.not_future.__func__)

    @model_validator(mode="after")
    def at_least_one(self):
        if all(x is None for x in (self.eps,self.book_per_share,self.dividend_per_share)):
            raise ValueError("请至少填写一个每股指标；缺失项留空，不能填零代替")
        return self


def valuation(store, sid):
    rows = store.rows("SELECT v.*,s.currency AS quote_currency,e.title,e.url,e.verification FROM valuation_inputs v "
                      "JOIN securities s ON s.id=v.security_id JOIN evidence e ON e.id=v.evidence_id WHERE v.security_id=?", (sid,))
    result = {"inputs":rows[0] if rows else None,"pe":None,"pb":None,"dividend_yield":None,
              "quote":None,"fx":None,"warnings":[],"formulas":{"pe":"股价 / 同币种每股收益",
                  "pb":"股价 / 同币种每股净资产","dividend_yield":"全年每股现金股息 / 同币种股价 × 100%"}}
    if not rows:
        result["warnings"].append("尚无带来源的每股财务指标；不推测估值数字。")
        return result
    item=rows[0]
    quotes=store.rows("SELECT * FROM quotes WHERE security_id=?", (sid,))
    if not quotes:
        result["warnings"].append("缺少股价，无法计算估值。")
        return result
    quote=quotes[0]
    result["quote"]=quote
    factor=Decimal(1)
    today=(datetime.now(timezone.utc)+timedelta(hours=8)).date()
    if (today-date.fromisoformat(quote["as_of"])).days>4:
        result["warnings"].append("股价已超过四个日历日，以下仅按存储报价重算。")
    if item["currency"] != item["quote_currency"]:
        fx=store.rows("SELECT * FROM fx WHERE currency='HKD'")
        if not fx:
            result["warnings"].append("财报与股价币种不同，缺少港币汇率，不能直接相除。")
            return result
        result["fx"]=fx[0]
        rate=dec(fx[0]["rate"])
        factor=rate if item["quote_currency"]=="CNY" else Decimal(1)/rate
        if (today-date.fromisoformat(fx[0]["as_of"])).days>4:
            result["warnings"].append("换算汇率已超过四个日历日，需更新后判断。")
    for field,out in (("eps","pe"),("book_per_share","pb"),("dividend_per_share","dividend_yield")):
        value=item[field]
        if value is None:
            continue
        number=dec(value)*factor
        if out=="dividend_yield":
            result[out]=money(number/dec(quote["price"])*100)
        elif number>0:
            result[out]=money(dec(quote["price"])/number)
        else:
            result["warnings"].append("每股收益非正，PE不适用；不能当作低估。" if out=="pe" else "每股净资产非正，PB不适用。")
    result["warnings"].append(("指标由聚合来源自动获取，尚待与财报核对；" if item["verification"]=="aggregated" else "指标由手动资料录入，尚待核实；")+"EPS口径需与股份拆并一致，历史现金股息不代表未来收益。")
    return result


def portfolio(store):
    positions = store.rows("SELECT s.*,p.quantity,p.cost,p.note,p.updated_at,q.price,q.previous,"
                           "q.as_of,q.source,q.fetched_at FROM positions p JOIN securities s ON s.id=p.security_id "
                           "LEFT JOIN quotes q ON s.id=q.security_id ORDER BY s.name")
    cash = store.rows("SELECT * FROM cash ORDER BY currency")
    fx = store.rows("SELECT * FROM fx WHERE currency='HKD'")
    rate = dec(fx[0]["rate"]) if fx else None
    total = Decimal(0)
    complete = True
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    for p in positions:
        p["stale"] = bool(p["as_of"] and (today - date.fromisoformat(p["as_of"])).days > 4)
        if p["price"] is None:
            p.update(market_value=None, gain=None, base_value=None)
            complete = False
            continue
        value = dec(p["price"]) * dec(p["quantity"])
        p["market_value"] = money(value)
        p["gain"] = money((dec(p["price"]) - dec(p["cost"])) * dec(p["quantity"]))
        conversion = Decimal(1) if p["currency"] == "CNY" else rate
        p["base_value"] = money(value * conversion) if conversion else None
        if conversion:
            total += value * conversion
        else:
            complete = False
    for c in cash:
        conversion = Decimal(1) if c["currency"] == "CNY" else rate
        c["base_value"] = money(dec(c["amount"]) * conversion) if conversion else None
        if conversion:
            total += dec(c["amount"]) * conversion
        elif dec(c["amount"]) > 0:
            complete = False
    for p in positions:
        p["weight"] = money(dec(p["base_value"]) / total * 100) if complete and total and p["base_value"] else None
    return {"positions": positions, "cash": cash, "fx": fx[0] if fx else None,
            "fx_metadata":store.settings().get("fx_metadata",{}),
            "fx_status":store.settings().get("fx_status",{}),
            "fx_stale": bool(fx and (today - date.fromisoformat(fx[0]["as_of"])).days > 4),
            "known_total": money(total), "complete": complete, "has_assets": bool(positions or cash),
            "valuation_note": "当前汇率估值；浮盈亏按录入成本计算，不含未提供的分红、费用和历史交易。"}
