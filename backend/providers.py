"""Read-only market/AI/message adapters with bounded network access."""
import json
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from urllib.parse import urlparse
import httpx
from .domain import dec


MODEL_MAX_OUTPUT_TOKENS = 32768


class ProviderError(Exception):
    def __init__(self,message,unbilled=False):
        super().__init__(message);self.unbilled=unbilled


class Credentials:
    """Windows uses Credential Manager. Development platforms retain keys in memory only."""
    def __init__(self):
        self.memory = {}
        self.persisted = sys.platform == "win32"

    def get(self, kind):
        env = os.getenv("KIMI_API_KEY" if kind == "kimi" else "SERVERCHAN_SENDKEY")
        if env:
            return env
        if kind in self.memory:
            return self.memory[kind]
        if self.persisted:
            try:
                from keyring.backends.Windows import WinVaultKeyring
                return WinVaultKeyring().get_password("RetirementWealth", kind) or ""
            except Exception:
                return ""
        return ""

    def set(self, kind, value):
        if self.persisted:
            try:
                from keyring.backends.Windows import WinVaultKeyring
                ring = WinVaultKeyring()
                if value:
                    ring.set_password("RetirementWealth", kind, value)
                elif ring.get_password("RetirementWealth", kind):
                    ring.delete_password("RetirementWealth", kind)
            except Exception as exc:
                raise ProviderError("Windows 凭据管理器保存失败；未将密钥写入普通文件。") from exc
        self.memory[kind] = value


class Market:
    def __init__(self):
        self.client = httpx.Client(timeout=httpx.Timeout(12, connect=6), follow_redirects=False,
                                   headers={"User-Agent": "Mozilla/5.0 RetirementWealth/0.1"})

    def lookup(self, text):
        text = text.strip()
        if not text:
            return []
        try:
            r = self.client.get("https://searchapi.eastmoney.com/api/suggest/get",
                                params={"input": text, "type": 14, "count": 8})
            r.raise_for_status()
            rows = r.json().get("QuotationCodeTable", {}).get("Data", []) or []
            result = []
            for row in rows:
                code = str(row.get("Code", ""))
                qt = str(row.get("QuoteID", ""))
                if (qt.startswith("116.") and code.isdigit() and len(code) <= 5
                        and str(row.get("TypeUS")) == "3" and not code.zfill(5).startswith("8")):
                    exchange = "HK"
                    code = code.zfill(5)
                elif len(code) == 6 and code.isdigit() and str(row.get("SecurityType")) in ("1", "2"):
                    exchange = "SH" if qt.startswith("1.") else ("BJ" if code[0] in "489" else "SZ")
                else:
                    continue
                result.append({"exchange": exchange, "ticker": code, "name": row["Name"],
                               "currency": "HKD" if exchange == "HK" else "CNY"})
            return result
        except Exception as exc:
            raise ProviderError("证券搜索暂不可用。可按交易所、代码和名称手动录入。") from exc

    def quote(self, security):
        try:
            return self._tencent_quote(security)
        except ProviderError:
            return self._eastmoney_quote(security)

    def _tencent_quote(self, security):
        prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj", "HK": "hk"}[security["exchange"]]
        try:
            response = self.client.get("https://qt.gtimg.cn/q=" + prefix + security["ticker"])
            response.raise_for_status()
            text = response.content.decode("gb18030")
            fields = text.split('"')[1].split("~")
            if fields[2] != security["ticker"]:
                raise ValueError("symbol mismatch")
            price, previous = dec(fields[3]), dec(fields[4])
            stamp = fields[30]
            time = datetime.strptime(stamp, "%Y/%m/%d %H:%M:%S" if security["exchange"] == "HK" else "%Y%m%d%H%M%S")
            if price <= 0 or previous <= 0 or time.date() > (datetime.now(timezone.utc)+timedelta(hours=8)).date():
                raise ValueError("invalid quote")
            return {"price":str(price), "previous":str(previous), "as_of":str(time.date()),
                    "source":"腾讯公开报价（可能延迟，时间 " + stamp + "）", "quoted_at":time.replace(tzinfo=timezone(timedelta(hours=8))).isoformat(), "precision":"second", "delay_seconds":None, "market_state":"unknown"}
        except Exception as exc:
            raise ProviderError("行情来源暂不可用，保留上次数据；可录入带来源和日期的报价。") from exc

    def _eastmoney_quote(self, security):
        market = "116" if security["exchange"] == "HK" else ("1" if security["exchange"] == "SH" else "0")
        params = {"secid": f'{market}.{security["ticker"]}', "klt": 101, "fqt": 0, "lmt": 3,
                  "end": "20500101", "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"}
        try:
            r = self.client.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params)
            r.raise_for_status()
            data = r.json().get("data") or {}
            bars = data.get("klines") or []
            if not bars:
                raise ValueError("empty")
            current = bars[-1].split(",")
            value = dec(current[2])
            previous = dec(bars[-2].split(",")[2]) if len(bars) > 1 else None
            if value <= 0:
                raise ValueError("bad price")
            day = datetime.fromisoformat(current[0]).date()
            today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
            if day > today:
                raise ValueError("future quote")
            return {"price": str(value), "previous": str(previous) if previous else None,
                    "as_of": str(day), "source": "东方财富日线（未复权；当日数据可能尚未收盘）", "precision":"date_only", "quoted_at":None, "delay_seconds":None, "market_state":"unknown"}
        except Exception as exc:
            raise ProviderError("行情来源暂不可用，保留上次数据；可录入带来源和日期的报价。") from exc

    def announcements(self, security):
        # Aggregator titles are leads, never a substitute for company disclosure body.
        try:
            r = self.client.get("https://np-anotice-stock.eastmoney.com/api/security/ann",
                                params={"page_size": 5, "page_index": 1, "ann_type": "A",
                                        "stock_list": security["ticker"]})
            r.raise_for_status()
            rows = (r.json().get("data") or {}).get("list") or []
            result = []
            for item in rows:
                codes = item.get("codes") or []
                if not any(str(x.get("stock_code", "")).zfill(5 if security["exchange"] == "HK" else 6)
                           == security["ticker"] for x in codes):
                    continue
                code = item.get("art_code")
                if not code or not str(code).isalnum():
                    continue
                title = item["title"]
                result.append({"title": title,
                               "url": f'https://data.eastmoney.com/notices/detail/{security["ticker"]}/{code}.html',
                               "published_at": item["notice_date"][:10], "content": title,
                               "kind": "announcement", "verification": "title_only"})
            return result
        except Exception as exc:
            raise ProviderError("公告检查暂不可用，无法据此判断没有重要公告。") from exc

    def official_text(self, url):
        """Download only known disclosure hosts, bounded size, redirects refused (SSRF boundary)."""
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            raise ProviderError("来源链接格式无效，请填写官方 PDF 直链。") from exc
        host = parsed.hostname or ""
        allowed = ("static.cninfo.com.cn", "www.hkexnews.hk", "www1.hkexnews.hk",
                   "www.sse.com.cn", "reportdocs.static.szse.cn")
        approved_netlocs = set(allowed) | {h + ":443" for h in allowed}
        if parsed.scheme != "https" or host not in allowed or parsed.netloc.lower() not in approved_netlocs:
            raise ProviderError("自动导入仅接受巨潮、交易所或披露易的官方 PDF 直链；其他资料请粘贴原文。")
        try:
            with self.client.stream("GET", url) as r:
                r.raise_for_status()
                parts, size = [], 0
                for part in r.iter_bytes():
                    size += len(part)
                    if size > 32 * 1024 * 1024:
                        raise ProviderError("PDF大于32MB，系统需改用官方网页或关键章节。")
                    parts.append(part)
            blob = b"".join(parts)
            if not blob.startswith(b"%PDF"):
                raise ProviderError("该链接不是 PDF 直链，请打开公告原文获取 PDF 地址。")
            from .pdf_text import extract
            text=extract(blob)
            if not text.strip():raise ProviderError('官方PDF没有可读内容，系统会尝试备用资料。')
            return text
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("官方 PDF 获取失败，未产生研究事实；可以粘贴资料原文。") from exc


class Kimi:
    def __init__(self, credentials):
        self.credentials = credentials
        self.client = httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False)

    def complete(self, model, messages, max_tokens=MODEL_MAX_OUTPUT_TOKENS):
        key = self.credentials.get("kimi")
        if not key:
            raise ProviderError("尚未配置 Kimi 开放平台密钥。请在维护设置中配置。")
        try:
            r = self.client.post("https://api.moonshot.cn/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {key}"},
                                 json={"model": model, "messages": messages, "max_tokens": max_tokens,
                                       "thinking": {"type": "disabled"},
                                       "response_format": {"type": "json_object"}})
            r.raise_for_status()
            result = r.json()
            usage = result.get("usage")
            if not usage:
                raise ProviderError("模型未返回用量记录；本次按预留上限计费记录。")
            choice=result["choices"][0]
            content = choice["message"]["content"]
            fenced=re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n```\s*",content,re.S|re.I)
            if fenced:content=fenced.group(1)
            try:
                payload=json.loads(content)
                if choice.get("finish_reason")=="length":payload["partial_output"]=True
                return payload, usage
            except json.JSONDecodeError:
                if not content.strip():raise ProviderError('模型没有返回正文。')
                return {"title":"研究章节", "summary":"模型正文已保留，结构化整理未完成。", "support":[{"text":content,"evidence_ids":[]}], "unknowns":["输出达到单次限制" if choice.get('finish_reason')=='length' else "返回格式未完成"], "partial_output":True},usage
        except ProviderError:
            raise
        except Exception as exc:
            # Never propagate provider bodies: they may contain credentials or private input.
            raise ProviderError("Kimi 请求或报告格式失败，请检查账号权限、余额和网络。本次费用保守记录。") from exc

    def tool(self,name,payload):
        if name not in ('search_pro','fetch'):raise ProviderError('不支持此联网工具。')
        key=self.credentials.get('kimi')
        if not key:raise ProviderError('Kimi尚未配置。')
        try:
            r=self.client.post('https://api.moonshot.cn/v1/tools/'+name,headers={'Authorization':'Bearer '+key},json=payload)
            r.raise_for_status()
            result=r.json()
            if not isinstance(result,dict):raise ValueError('invalid')
            return result
        except Exception as exc:raise ProviderError('联网工具暂未完成，请核对网络和账户权限；不会自动重复付费。') from exc


class Push:
    def __init__(self, credentials):
        self.credentials = credentials
        self.client = httpx.Client(timeout=20, follow_redirects=False)

    def send(self, title, content):
        key = self.credentials.get("push")
        if not key:
            raise ProviderError("微信推送未配置，请在维护设置中填写 Server酱 SendKey。")
        if not key.startswith("SCT") or not key.isalnum():
            raise ProviderError("仅支持 Server酱 Turbo 的 SCT 密钥，请核对。")
        try:
            r = self.client.post(f"https://sctapi.ftqq.com/{key}.send", data={"title": title, "desp": content})
            r.raise_for_status()
            if r.json().get("code") != 0:
                raise ProviderError("推送服务拒绝请求，请检查额度及接收绑定。")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("推送结果不明，请检查微信；系统不会自动重复发送这条消息。") from exc
