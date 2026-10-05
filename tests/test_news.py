from unittest.mock import Mock
import pytest
from backend.news import parse_feed,publisher,news_feed,refresh_news
from backend.storage import Store
from backend.providers import ProviderError

def feed(date='Mon, 05 Oct 2026 08:00:00 +0800',link='https://www.news.gov.hk/tc/a.htm'):
    return f'<rss><channel><item><title>财经发布</title><link>{link}</link><pubDate>{date}</pubDate><description>&lt;p&gt;官方正文&amp;nbsp;&lt;/p&gt;</description></item></channel></rss>'.encode()

def test_rss_identity_date_and_plain_description():
    item=parse_feed(feed())[0]
    assert item['published_at']=='2026-10-05T00:00:00+00:00'
    assert item['summary']=='官方正文' and item['category']=='official'
    assert parse_feed(feed(date='unknown'))[0]['published_at']==''
    assert parse_feed(feed(link='https://news.gov.hk.evil.example/a'))==[]
    assert publisher('https://evilgov.hk/a')[1]=='media'
    assert publisher('https://www.hkexnews.hk/a')[1]=='official'

@pytest.mark.parametrize('xml',[b'<!DOCTYPE foo><rss/>',b'<!ENTITY x "test"><rss/>',b'x'*2_000_001])
def test_reject_xml_expansion_and_unbounded_feed(xml):
    with pytest.raises(ValueError):parse_feed(xml)

def test_failed_fetch_retains_cache(tmp_path):
    store=Store(tmp_path);store.save_settings({'news_feed':parse_feed(feed())})
    client=Mock();client.get.side_effect=TimeoutError()
    with pytest.raises(ProviderError):refresh_news(store,client)
    assert len(news_feed(store))==1
    assert store.settings()['news_status']['status']=='failed'

def test_refresh_updates_cache_without_ai(tmp_path):
    store=Store(tmp_path);client=Mock();client.get.return_value.content=feed()
    assert refresh_news(store,client) is None
    assert store.settings()['news_status']['status']=='done'

def test_feed_filters_unknown_media_manual_and_context_and_deduplicates(tmp_path):
    store=Store(tmp_path)
    sid=store.add_security({'exchange':'HK','ticker':'00700','name':'测试公司'})
    cases=[('市场新闻','https://finance.eastmoney.com/a','news','search_excerpt'),
           ('个人博客','https://blog.example.com/a','news','search_excerpt'),
           ('[行业/同业背景] 不相关研究','https://finance.eastmoney.com/b','news','search_excerpt'),
           ('手动官方链接','https://www.gov.hk/manual','news','manual'),
           ('公告','https://www.hkexnews.hk/a','announcement','title_only')]
    for title,url,kind,status in cases:
        store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
                      (sid,title,url,'2026-10-04','正文',kind,status,'2026-10-04'))
    items=news_feed(store)
    assert {x['title'] for x in items}=={'市场新闻','公告'}
    assert next(x for x in items if x['title']=='公告')['category']=='announcement'
