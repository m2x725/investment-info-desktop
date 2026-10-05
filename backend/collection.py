"""Public disclosure discovery. No guessed issuer IDs, no search-engine snippets as evidence."""
import html
import json
import re
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin
from .providers import ProviderError
from .domain import dec
from .signals import disclosure_signal


def today():
    return (datetime.now(timezone.utc)+timedelta(hours=8)).date()


def clean(value):
    return html.unescape(re.sub(r"<[^>]*>", " ", str(value))).strip()


def choose(rows):
    # Retain the latest full annual report and latest interim/quarterly report, plus two recent notices.
    result=[]
    for pattern in (r"年度报告|年度報告|年報|Annual Report",r"半年度报告|半年度報告|中期報告|季度报告|季度報告|Interim Report"):
        candidates=[r for r in rows if re.search(pattern,r["title"],re.I) and not re.search("摘要|Summary|環境|社会|社會",r["title"],re.I)]
        if pattern.startswith("年度"):
            candidates=[r for r in candidates if not re.search("半年度",r["title"])]
        candidates=list({r["url"]:r for r in candidates}.values())
        if candidates:
            result.extend(candidates[:3] if pattern.startswith("年度") else candidates[:1])
    for row in sorted(rows,key=lambda r:disclosure_signal(r['title'])[0]!='high'):
        if re.search(r"年度报告|年度報告|年報|Annual Report|中期報告|季度报告|Interim Report|摘要|Summary",row["title"],re.I):
            continue
        if row["url"] not in [r["url"] for r in result] and len(result)<6:
            result.append(row)
    return result


class Collector:
    def __init__(self,market):
        self.market=market
        self.client=market.client
        self.cn_ids=None
        self.hk_ids={}

    def documents(self,security):
        try:
            rows=self.hk_documents(security) if security["exchange"]=="HK" else self.cn_documents(security)
            ordered=sorted(rows,key=lambda r:r["published_at"],reverse=True)
            selected=choose(ordered)
            # Preserve remaining metadata so a serious notice is not lost behind the four-PDF download cap.
            seen={r['url'] for r in selected}
            for row in ordered:
                if row['url'] not in seen:
                    selected.append(row);seen.add(row['url'])
            return selected
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("官方资料查询暂不可用，系统会保留已有原文并在下次更新重试。") from exc

    def cn_documents(self,s):
        if self.cn_ids is None:
            r=self.client.get("https://www.cninfo.com.cn/new/data/szse_stock.json");r.raise_for_status()
            self.cn_ids={x["code"]:x["orgId"] for x in r.json()["stockList"]}
        if s["ticker"] not in self.cn_ids:
            raise ProviderError("官方查询尚未匹配这只证券，未使用同名公司的资料。")
        payload={"pageNum":"1","pageSize":"60","column":"szse","tabName":"fulltext",
                 "stock":s["ticker"]+","+self.cn_ids[s["ticker"]],"isHLtitle":"false",
                 "seDate":str(today()-timedelta(days=1460))+"~"+str(today())}
        # Separate financial query prevents frequent ordinary notices hiding the annual report.
        rows=[]
        for category in ("category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh",""):
            r=self.client.post("https://www.cninfo.com.cn/new/hisAnnouncement/query",data={**payload,"searchkey":"","category":category})
            r.raise_for_status()
            for x in r.json().get("announcements") or []:
                if x.get("secCode")!=s["ticker"] or str(x.get("adjunctType","")).upper()!="PDF":
                    continue
                path=x.get("adjunctUrl","")
                if not re.fullmatch(r"finalpage/[\d-]+/\d+\.[pP][dD][fF]",path):
                    continue
                day=datetime.fromtimestamp(x["announcementTime"]/1000,timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
                if day>today():continue
                title=clean(x["announcementTitle"])
                rows.append(dict(title=title,url="https://static.cninfo.com.cn/"+path,published_at=str(day),
                                 kind="financial" if re.search("年度报告|季度报告",title) else "announcement"))
        return rows

    def hk_documents(self,s):
        if s["ticker"] not in self.hk_ids:
            r=self.client.get("https://www1.hkexnews.hk/search/prefix.do",
                              params={"lang":"ZH","type":"A","name":s["ticker"],"market":"SEHK","callback":"callback"})
            r.raise_for_status()
            match=re.fullmatch(r"\s*callback\((.*)\);\s*",r.text,re.S)
            if not match:raise ProviderError("披露易证券身份查询未返回可识别数据。")
            stocks=json.loads(match[1]).get("stockInfo",[])
            matches=[x for x in stocks if str(x["code"]).zfill(5)==s["ticker"]]
            if len(matches)!=1:raise ProviderError("披露易未唯一匹配股票代码，未获取其他公司的资料。")
            self.hk_ids[s["ticker"]]=matches[0]["stockId"]
        params={"sortDir":"0","sortByOptions":"DateTime","category":"0","market":"SEHK",
                "stockId":self.hk_ids[s["ticker"]],"documentType":"-1","t2Gcode":"-2","t2code":"-2",
                "searchType":"0","fromDate":(today()-timedelta(days=1460)).strftime("%Y%m%d"),
                "toDate":today().strftime("%Y%m%d"),"rowRange":"100","lang":"ZH"}
        rows=[]
        for category in ("40000","-2"):
            r=self.client.get("https://www1.hkexnews.hk/search/titleSearchServlet.do",params={**params,"t1code":category})
            r.raise_for_status()
            data=json.loads(r.json().get("result","[]"))
            for x in data:
                if s["ticker"] not in re.findall(r"\d{5}",clean(x.get("STOCK_CODE",""))) or x.get("FILE_TYPE")!="PDF":
                    continue
                path=x.get("FILE_LINK","")
                if not re.fullmatch(r"/listedco/listconews/sehk/[\w/.-]+\.pdf",path,re.I):continue
                day=datetime.strptime(x["DATE_TIME"],"%d/%m/%Y %H:%M").date()
                if day>today():continue
                title=clean(x["TITLE"])
                rows.append(dict(title=title,url=urljoin("https://www.hkexnews.hk",path),published_at=str(day),
                                 kind="financial" if category=="40000" else "announcement"))
        return rows

    def financials(self,s):
        """Secondary structured data; never trust HK indicator's nominal quote currency."""
        hk=s["exchange"]=="HK"
        symbol=s["ticker"]+("." + s["exchange"])
        endpoint="https://datacenter.eastmoney.com/securities/api/data/v1/get" if hk else "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params={"reportName":"RPT_HKF10_FN_MAININDICATOR" if hk else "RPT_F10_FINANCE_MAINFINADATA",
                "columns":"HKF10_FN_MAININDICATOR" if hk else "ALL",
                "filter":f'(SECUCODE="{symbol}")'+('(DATE_TYPE_CODE="001")' if hk else '(REPORT_TYPE="年报")'),
                "sortColumns":"STD_REPORT_DATE" if hk else "REPORT_DATE","sortTypes":"-1","pageSize":"1",
                "source":"F10","client":"PC"}
        try:
            r=self.client.get(endpoint,params=params);r.raise_for_status()
            data=(r.json().get("result") or {}).get("data") or []
            if not data or data[0].get("SECUCODE")!=symbol:raise ValueError("identity")
            row=data[0];as_of=row["REPORT_DATE"][:10];currency=row.get("CURRENCY")
            if hk:
                r=self.client.get(endpoint,params={"reportName":"RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY",
                    "columns":"SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE",
                    "filter":f'(SECUCODE="{symbol}")',"source":"F10","client":"PC"});r.raise_for_status()
                summaries=(r.json().get("result") or {}).get("data") or []
                match=[v for group in summaries for v in group.get("REPORT_LIST",[])
                       if v.get("SECUCODE")==symbol and v.get("REPORT_DATE","")[:10]==as_of]
                if not match:raise ValueError("currency unconfirmed")
                currency=match[0]["CURRENCY"]
            currency={"人民币":"CNY","港元":"HKD","港币":"HKD"}.get(currency,currency)
            if currency not in ("CNY","HKD") or as_of>str(today()):raise ValueError("currency/date")
            values={}
            for source,target in (("BASIC_EPS" if hk else "EPSJB","eps"),("BPS","book_per_share")):
                val=row.get(source)
                values[target]=str(dec(val).quantize(Decimal(".000001"),rounding=ROUND_HALF_UP)) if val is not None else None
            return {**values,"dividend_per_share":None,"currency":currency,"as_of":as_of,
                    "report_period":as_of[:4]+"年度","earnings_basis":"annual",
                    "url":"https://emweb.securities.eastmoney.com/PC_HKF10/FinancialAnalysis/index?type=web&code="+s["ticker"] if hk
                          else "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code="+s["exchange"]+s["ticker"],
                    "publication":row.get("NOTICE_DATE","")[:10],
                    "locator":"东方财富年度基本每股收益/每股净资产；聚合数据，非独立核实"}
        except Exception as exc:
            raise ProviderError("自动财务指标暂不可用或币种无法确认，估值缺失项保留未知。") from exc

    def fx(self):
        try:
            r=self.client.get("https://api.frankfurter.dev/v2/providers/ecb/rate/hkd/cny");r.raise_for_status()
            data=r.json()
            if data["base"].upper()!="HKD" or data["quote"].upper()!="CNY" or date.fromisoformat(data["date"])>today() or dec(data["rate"])<=0:
                raise ValueError("invalid rate")
            return {"rate":str(data["rate"]),"as_of":data["date"],"source":"ECB参考汇率，经Frankfurter；非交易报价"}
        except Exception as exc:
            raise ProviderError("自动汇率暂不可用，保留上次数据并标明日期。") from exc
