"""Public official RSS and existing company sources. No AI calls or inferred dates."""
import re
import hashlib,json
from html import unescape
from email.utils import parsedate_to_datetime
from datetime import timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from .storage import utcnow
from .providers import ProviderError

FEED = 'https://www.news.gov.hk/tc/categories/finance/html/articlelist.rss.xml'

def publisher(url):
    try:host=(urlparse(url).hostname or '').lower()
    except ValueError:return '', 'media'
    official=('gov.hk','gov.cn','hkexnews.hk','hkex.com.hk','sse.com.cn','szse.cn','cninfo.com.cn')
    is_official=any(host==d or host.endswith('.'+d) for d in official)
    return host, 'official' if is_official else 'media'

def parse_feed(content):
    if len(content)>2_000_000 or re.search(br'<!DOCTYPE|<!ENTITY',content,re.I):
        raise ValueError('invalid feed')
    root=ET.fromstring(content);items=[]
    for item in root.findall('.//item')[:50]:
        url=(item.findtext('link') or '').strip(); title=(item.findtext('title') or '').strip()
        host,category=publisher(url)
        if not title or urlparse(url).scheme!='https' or not(host=='news.gov.hk' or host.endswith('.news.gov.hk')):continue
        raw=item.findtext('pubDate') or '';published=''
        try:
            dt=parsedate_to_datetime(raw)
            if dt.tzinfo:published=dt.astimezone(timezone.utc).isoformat()
        except (ValueError,TypeError,OverflowError):pass
        description=item.findtext('description') or ''
        summary=unescape(re.sub(r'<[^>]*>','',description)).strip()
        items.append(dict(id='rss:'+url,title=title,url=url,publisher='香港政府新闻公报',category=category,
                          published_at=published,summary=summary,verification='rss',collected_at=utcnow()))
    return items

def refresh_news(store,client):
    try:
        response=client.get(FEED);response.raise_for_status()
        items=parse_feed(response.content)
        if not items:raise ValueError('empty feed')
    except Exception:
        store.save_settings({'news_status':{'checked_at':utcnow(),'status':'failed','message':'官方新闻未更新，保留上次资料。'}})
        raise ProviderError('官方新闻暂时无法获取，已保留上次资料。')
    store.save_settings({'news_feed':items,'news_status':{'checked_at':utcnow(),'status':'done','message':'官方新闻已更新'}})
    return None

def news_feed(store):
    items=list(store.settings().get('news_feed',[]))
    rows=store.rows("SELECT e.id,e.title,e.url,e.published_at,e.kind,e.verification,e.content,s.name AS company "
                    "FROM evidence e JOIN securities s ON s.id=e.security_id "
                    "WHERE e.kind IN ('announcement','news') ORDER BY e.published_at DESC,e.id DESC LIMIT 100")
    for e in rows:
        host,category=publisher(e['url'])
        if e['title'].startswith('[行业/同业背景]'):continue
        media=('news.cn','xinhuanet.com','cctv.com','reuters.com','apnews.com','stcn.com','cs.com.cn','yicai.com','caixin.com','eastmoney.com','aastocks.com','finance.sina.com.cn','hket.com','etnet.com.hk','scmp.com','futunn.com')
        if category=='media' and not any(host==d or host.endswith('.'+d) for d in media):continue
        # A manually supplied link is not treated as independently collected official news.
        if e['verification'] not in ('official_download','title_only','web_retrieved','search_excerpt'):continue
        if e['kind']=='announcement' and category=='official':category='announcement'
        items.append({**{k:v for k,v in e.items() if k!='content'},'id':'evidence:'+str(e['id']),'publisher':host,'category':category,'content_hash':hashlib.sha256(e['content'].encode()).hexdigest(),'summary':digest_excerpt(e['content'],e['title'],e['verification'])})
    unique={}
    for item in sorted(items,key=lambda x:x.get('published_at') or '',reverse=True):
        if item['url'] not in unique:unique[item['url']]=item
    # Keep every source, but place company-linked material ahead of unrelated RSS.
    # This is transparent title-based ranking, not an AI materiality judgement.
    def relevance(item):
        title=item['title']
        routine=bool(re.search('翌日披露|月報|月报',title))
        important=bool(re.search('盈利警告|盈警|业绩|業績|年度报告|年度報告|中期|收购|收購|调查|調查|违约|違約',title))
        return (bool(item.get('company')) and not routine,important,not routine,item.get('published_at') or '')
    unique=dict(sorted(unique.items(),key=lambda pair:relevance(pair[1]),reverse=True))
    analyses={}
    for row in store.rows("SELECT id,payload,created_at FROM reports WHERE kind='news_analysis' ORDER BY id DESC"):
        payload=json.loads(row['payload']);analyses.setdefault(payload.get('news_key'),{**row,'payload':payload})
    return [{**item,'summary':unescape(item.get('summary','')),'analysis':analyses.get(news_key(item))} for item in list(unique.values())[:60]]


def news_key(item):
    return hashlib.sha256(json.dumps([item['id'],item['title'],item['url'],item.get('published_at'),item.get('summary',''),item.get('content_hash')],ensure_ascii=False).encode()).hexdigest()


def digest_excerpt(content,title,verification):
    from .research_engine import readable
    if verification=='title_only':return '仅有标题，尚未取得正文；不能据此判断具体变化。'
    if not readable(content):return '正文解析不足，暂时无法提炼要点，请查看原文。'
    if re.search(r'翌日披露|翌日披露',title):
        topics=[]
        if re.search(r'已發行股份|已发行股份',content):topics.append('已发行股份变动')
        if re.search(r'購回|回购',content):topics.append('股份回购')
        if re.search(r'股份獎勵|股份奖励|購股權|购股权',content):topics.append('股权激励相关发行')
        if topics:return '本次披露包含'+ '、'.join(topics)+'记录。表格中的日期、数量和金额需逐项核对，可点击 AI 总结提炼具体变化，或直接查看原文。'
    text=re.sub(r'\[第\d+页\]','',content)
    text=re.sub(r'[ \t\r]+',' ',text).strip()
    sentences=[x.strip() for x in re.split(r'(?<=[。！？；])|\n',text) if len(x.strip())>12]
    ranked=sorted(enumerate(sentences),key=lambda x:-(len(re.findall(r'回购|購回|收入|盈利|利润|利潤|现金|現金|董事|股息|增长|增長|减少|減少|政策|监管|監管|股份',x[1]))+bool(re.search(r'\d',x[1]))))
    chosen=sorted(ranked[:2])
    result=' '.join(x[1] for x in chosen) if chosen else text
    return result[:600]+('…' if len(result)>600 else '')
