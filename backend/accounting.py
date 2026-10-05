"""Deterministic CNY ledger accounting. Broker cost is not an acquisition price."""
import json,math
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from .domain import dec,money,portfolio
from .providers import ProviderError
from .storage import utcnow
ZERO=Decimal(0)

def ledger_state(rows):
    positions={};cash=ZERO;net=ZERO;realized=ZERO;income=ZERO;fees=ZERO;flows=defaultdict(lambda:ZERO)
    for r in sorted(rows,key=lambda r:(r['day'],r['id'])):
        kind=r['kind'];q=dec(r['quantity']);amount=dec(r['amount_cny']);fee=dec(r['fee_cny']);sid=r['security_id']
        payload=json.loads(r['payload']);gross=payload.get('amount_includes_fees',True)
        # Settlement amount already includes fees unless the importer explicitly says otherwise.
        paid=amount if gross else amount+fee
        received=amount if gross else amount-fee
        if kind in ('BUY','SELL','SPLIT'):
            p=positions.setdefault(sid,{'quantity':ZERO,'cost_cny':ZERO})
            if kind=='BUY':p['quantity']+=q;p['cost_cny']+=paid;cash-=paid
            elif kind=='SELL':
                if q>p['quantity']:raise ProviderError('流水缺少期初持仓或卖出数量超过已记录持仓；请补齐历史，暂按快照分析。')
                allocated=p['cost_cny']*q/p['quantity'];p['quantity']-=q;p['cost_cny']-=allocated;cash+=received;realized+=received-allocated
            else:
                if amount or fee:raise ProviderError('股份数量变更不能代替带交收金额的配股交易。')
                if p['quantity']+q<=0:raise ProviderError('股份变更后的数量必须大于零；请核对拆并股记录。')
                p['quantity']+=q
        elif kind=='DEPOSIT':cash+=amount;net+=amount;flows[r['day']]+=amount
        elif kind=='WITHDRAWAL':cash-=amount;net-=amount;flows[r['day']]-=amount
        elif kind in ('DIVIDEND','INTEREST'):cash+=received;income+=received
        elif kind=='FEE':cash-=amount;fees+=amount
    return {'positions':positions,'cash':cash,'net_investment':net,'realized_gain':realized,'income':income,'standalone_fees':fees,'flows':flows}

def xirr(rows,terminal,terminal_day):
    flows=[]
    for r in rows:
        if r['kind'] in ('DEPOSIT','WITHDRAWAL'):
            flows.append((date.fromisoformat(r['day']),float(dec(r['amount_cny']))*(-1 if r['kind']=='DEPOSIT' else 1)))
    flows.append((date.fromisoformat(terminal_day),float(terminal)))
    if not flows or not any(x[1]<0 for x in flows) or not any(x[1]>0 for x in flows):return None
    start=min(d for d,v in flows)
    if (date.fromisoformat(terminal_day)-start).days<=0:return None
    def npv(rate):return sum(v/(1+rate)**((d-start).days/365.0) for d,v in flows)
    # Find all brackets; ambiguous/multiple-root cashflows do not receive a single invented IRR.
    grid=[-0.999,-0.99,-0.9,-0.5,0,0.1,0.5,1,2,5,10,100,1000]
    roots=[r for r in grid if abs(npv(r))<1e-8]
    brackets=[(a,b) for a,b in zip(grid,grid[1:]) if a not in roots and b not in roots and npv(a)*npv(b)<0]
    if roots:return money(Decimal(str(roots[0]))*100) if len(roots)==1 and not brackets else None
    if len(brackets)!=1:return None
    lo,hi=brackets[0]
    for _ in range(100):
        mid=(lo+hi)/2
        if npv(lo)*npv(mid)<=0:hi=mid
        else:lo=mid
    return money(Decimal(str((lo+hi)/2))*100)

def overview(store):
    result=portfolio(store)
    result.update(account=store.rows('SELECT * FROM accounts WHERE id=?',('eastmoney',))[0],as_of=utcnow(),warnings=[],net_investment=None,total_gain=None,realized_gain=None,income=None,money_weighted_return=None,time_weighted_return=None,day_gain=None)
    broker={r['security_id']:{**{k:v for k,v in r.items() if k!='as_of'},'broker_as_of':r['as_of']} for r in store.rows('SELECT * FROM holding_snapshots')}
    for p in result['positions']:
        p.update(broker.get(p['id'],{}))
        p['accounting_cost_cny']=None;p['gain_cny']=None
        if p['id'] in broker:
            p['gain']=None # a negative/foreign broker cost is never treated as a normal purchase cost
            if p.get('cost_currency')=='CNY' and p.get('broker_cost') is not None and dec(p['broker_cost'])>=0 and p['base_value'] is not None:
                p['snapshot_cost_cny']=money(dec(p['broker_cost'])*dec(p['quantity']))
                p['snapshot_gain_cny']=money(dec(p['base_value'])-dec(p['snapshot_cost_cny']))
        else:
            p['broker_cost']=p['cost'];p['cost_currency']=p['currency']
            if dec(p['cost'])<0:p['gain']=None
    rows=store.rows('SELECT * FROM ledger WHERE account_id=? ORDER BY day,id',('eastmoney',))
    result['ledger_rows']=len(rows)
    result['coverage']='完整历史' if result['account']['history_complete'] else '持仓快照；历史收益未核算'
    if result['account']['mode']=='ledger' and result['account']['history_complete']:
        state=ledger_state(rows);securities={p['id']:p for p in result['positions']}
        rate=dec(result['fx']['rate']) if result['fx'] else None
        active=[];total=state['cash'];cost=ZERO;complete=True
        for sid,v in state['positions'].items():
            if v['quantity']==0:continue
            s=store.rows('SELECT * FROM securities WHERE id=?',(sid,))[0];q=store.rows('SELECT * FROM quotes WHERE security_id=?',(sid,));conversion=Decimal(1) if s['currency']=='CNY' else rate
            p={**s,**(q[0] if q else {}),'quantity':str(v['quantity']),'cost':str(v['cost_cny']/v['quantity']),'accounting_cost_cny':money(v['cost_cny']),'cost_currency':'CNY','gain':None,'stale':not q,'market_value':None,'base_value':None,'gain_cny':None,**broker.get(sid,{})}
            p['quantity']=str(v['quantity']);cost+=v['cost_cny']
            if q and conversion:
                value=dec(q[0]['price'])*v['quantity'];base=value*conversion;total+=base
                p.update(market_value=money(value),base_value=money(base),gain_cny=money(base-v['cost_cny']))
            else:complete=False
            active.append(p)
        for p in active:p['weight']=money(dec(p['base_value'])/total*100) if complete and total>0 and p['base_value'] is not None else None
        result.update(positions=active,cash=[{'currency':'CNY','amount':money(state['cash']),'base_value':money(state['cash'])}],known_total=money(total),complete=complete,has_assets=bool(active or state['cash']),net_investment=money(state['net_investment']),realized_gain=money(state['realized_gain']),income=money(state['income']),total_gain=money(total-state['net_investment']) if complete else None,money_weighted_return=xirr(rows,total,(datetime.now(timezone.utc)+timedelta(hours=8)).date().isoformat()) if complete else None)
        closing=store.rows('SELECT * FROM daily_values WHERE account_id=? ORDER BY day',('eastmoney',))
        if closing and complete:
            result['time_weighted_return']=time_weighted(closing,state['flows'])
            prior=[r for r in closing if r['day']<datetime.fromisoformat(utcnow()).date().isoformat()]
            if prior:
                last=prior[-1];today=(datetime.now(timezone.utc)+timedelta(hours=8)).date().isoformat()
                result['day_gain']=money(total-dec(last['value_cny'])-sum((v for d,v in state['flows'].items() if d>last['day']),ZERO)) if last['day']==previous_weekday(today) and all(p.get('as_of')==today for p in active) else None
        result['warnings'].append('资金加权收益率按实际出入金日期；时间加权收益率需完整每日估值，目前缺失时不输出。')
    else:result['warnings'].append('累计净投入、历史收益和当日账户损益需要完整流水及期初估值；券商显示盈亏单独保留。')
    for p in result['positions']:
        meta=store.rows('SELECT * FROM quote_metadata WHERE security_id=?',(p['id'],))
        p['quote_metadata']=meta[0] if meta else {'precision':'date_only','quoted_at':None,'delay_seconds':None,'market_state':'unknown','timezone':'Asia/Shanghai'}
    stamps=[p['quote_metadata'].get('quoted_at') for p in result['positions'] if p['quote_metadata'].get('quoted_at')]
    result['quote_time_range']={'earliest':min(stamps) if stamps else None,'latest':max(stamps) if stamps else None,'missing_timestamps':len(result['positions'])-len(stamps)}
    if stamps and (max(datetime.fromisoformat(t) for t in stamps)-min(datetime.fromisoformat(t) for t in stamps)).total_seconds()>90:result['warnings'].append('本次报价时间跨度超过90秒，组合是采集快照，不是同一交易时刻。')
    if len(stamps)<len(result['positions']):result['warnings'].append('部分报价缺少时分秒，不能称为当前实时估值。')
    result['valuation_note']='人民币为账户核算币种；港元价格按注明日期的参考汇率估值，券商结算和显示口径单独保留。'
    return result

def activate(store,complete):
    if not complete:raise ProviderError('请确认已核对完整历史，包括期初持仓、出入金与费用。')
    state=ledger_state(store.rows('SELECT * FROM ledger ORDER BY day,id'))
    snapshots=store.rows('SELECT * FROM holding_snapshots')
    if not snapshots:raise ProviderError('请先导入当前持仓快照，用于核对流水计算的数量。')
    actual={r['security_id']:dec(r['quantity']) for r in snapshots if dec(r['quantity'])!=0}
    calculated={sid:p['quantity'] for sid,p in state['positions'].items() if p['quantity']!=0}
    if actual!=calculated:raise ProviderError('流水与当前快照数量不一致，保留快照模式；请补齐或修正记录。')
    store.execute("UPDATE accounts SET mode='ledger',history_complete=1 WHERE id='eastmoney'")
    return {'ok':True}

def scenarios(snapshot):
    values=[p for p in snapshot['positions'] if p.get('base_value') is not None]
    assets=sum((dec(p['base_value']) for p in values),ZERO)
    top=max(values,key=lambda p:dec(p['base_value']),default=None)
    hk=sum((dec(p['base_value']) for p in values if p['currency']=='HKD'),ZERO)
    return [{'name':'证券组合下跌10%','loss_cny':money(assets*Decimal('.1'))},{'name':'证券组合下跌20%','loss_cny':money(assets*Decimal('.2'))},{'name':'最大持仓下跌20%','loss_cny':money(dec(top['base_value'])*Decimal('.2')) if top else None},{'name':'港币相对人民币贬值5%（港元价格不变）','loss_cny':money(hk*Decimal('.05'))}]

def risk_analysis(store,snapshot):
    groups=defaultdict(lambda:ZERO);currencies=defaultdict(lambda:ZERO);warnings=[]
    for p in snapshot['positions']:
        if p.get('weight') is None:continue
        groups[p.get('industry') or '行业未分类']+=dec(p['weight']);currencies[p['currency']]+=dec(p['weight'])
    result={'scenarios':scenarios(snapshot),'industry_weights':{k:money(v) for k,v in groups.items()},'currency_weights':{k:money(v) for k,v in currencies.items()},'correlation':None,'risk_contribution':None,'observations':0,'warnings':warnings,'scenario_note':'假设情景而非预测；只计算已获取价格与汇率的证券资产，现金不随股价同比下跌。'}
    if not snapshot['complete']:
        warnings.append('价格或汇率缺失，情景金额仅覆盖可估值资产；统计风险暂不计算。')
        return result
    ids=[p['id'] for p in snapshot['positions']]
    histories={sid:{r['day']:float(r['close']) for r in store.rows("SELECT * FROM price_history WHERE security_id=? AND adjustment='qfq'",(sid,))} for sid in ids}
    common=sorted(set.intersection(*(set(h) for h in histories.values()))) if histories else []
    result['observations']=max(0,len(common)-1)
    fxrows=store.rows('SELECT * FROM fx_history ORDER BY day')
    if any(p['currency']=='HKD' for p in snapshot['positions']):
        if not fxrows:warnings.append('缺少历史汇率，不能把港元收益当成人民币收益。');return result
        for p in snapshot['positions']:
            if p['currency']!='HKD':continue
            converted={}
            for d,v in histories[p['id']].items():
                rates=[r for r in fxrows if r['day']<=d and (date.fromisoformat(d)-date.fromisoformat(r['day'])).days<=4]
                if rates:converted[d]=v*float(rates[-1]['rate'])
            histories[p['id']]=converted
        common=sorted(set.intersection(*(set(h) for h in histories.values()))) if histories else []
        result['observations']=max(0,len(common)-1)
    if len(common)<121:warnings.append('少于120个有效共同交易日，不输出相关性或统计风险结论。');return result
    try:
        import pandas as pd
        import riskfolio as rp
        prices=pd.DataFrame({sid:[histories[sid][d] for d in common] for sid in ids},index=common)
        returns=prices.pct_change().dropna()
        weights=[float(dec(p['weight'])/100) for p in snapshot['positions']]
        import numpy as np
        if not np.isfinite(returns.values).all() or (returns.std()<=1e-12).any():
            warnings.append('收益序列无波动或包含无效值，不能计算相关性。');return result
        contribution=rp.Risk_Contribution(w=np.array(weights).reshape(-1,1),cov=returns.cov().values,returns=returns,rm='MV')
        if not np.isfinite(contribution).all():raise ValueError('invalid risk')
        result['correlation']=returns.corr().to_dict();result['risk_contribution']={sid:float(v) for sid,v in zip(ids,contribution)}
        result['risk_note']='风险贡献为人民币日收益波动贡献，权重含现金；历史统计不是损失预测。'
    except ImportError:warnings.append('组合统计组件未安装；基础核算与情景分析仍可用。')
    except Exception:warnings.append('统计风险计算未完成，未生成替代指标。')
    return result


def time_weighted(closing,flows):
    """Exact linked return only when no intervening external flows; otherwise requires flow-time valuations."""
    if len(closing)<2:return None
    start,end=closing[0]['day'],closing[-1]['day']
    if any(v!=ZERO for d,v in flows.items() if start<d<=end):return None
    linked=Decimal(1)
    for before,after in zip(closing,closing[1:]):
        if dec(before['value_cny'])<=0:return None
        linked*=dec(after['value_cny'])/dec(before['value_cny'])
    return money((linked-1)*100)


def capture_close(store,now):
    """Do not label intraday or date-only public quotes as an account closing valuation."""
    if now.weekday()>=5 or now.strftime('%H:%M')<'16:30':return False
    snap=overview(store)
    if not snap['complete'] or snap['account']['mode']!='ledger':return False
    day=now.date().isoformat()
    for p in snap['positions']:
        stamp=p['quote_metadata'].get('quoted_at')
        if not stamp:return False
        when=datetime.fromisoformat(stamp)
        if when.date().isoformat()!=day or when.strftime('%H:%M')<('16:00' if p['currency']=='HKD' else '15:00'):return False
    store.execute('INSERT OR REPLACE INTO daily_values VALUES(?,?,?,?)',('eastmoney',day,snap['known_total'],'0'))
    return True


def previous_weekday(day):
    previous=date.fromisoformat(day)-timedelta(days=1)
    while previous.weekday()>=5:previous-=timedelta(days=1)
    return previous.isoformat()
