"""Reproducible financial formulas. Inputs/assumptions remain separate from evidence."""
from decimal import Decimal
from .domain import dec,money

def growth(current,previous):
    if current is None or previous is None or dec(previous)<=0:return None
    return money((dec(current)/dec(previous)-1)*100)

def dcf(cash_flows,discount_rate,terminal_growth,net_debt,shares):
    rate,g=dec(discount_rate),dec(terminal_growth)
    if rate<=g or rate<=0 or g<=-1 or dec(shares)<=0 or not cash_flows:raise ValueError('DCF需折现率大于永续增长率、正股数和现金流序列')
    flows=[dec(v) for v in cash_flows]
    if flows[-1]<=0:raise ValueError('永续增长DCF不适用于末期现金流非正的情景')
    present=sum((v/(1+rate)**(i+1) for i,v in enumerate(flows)),Decimal(0))
    terminal=flows[-1]*(1+g)/(rate-g)/(1+rate)**len(flows)
    equity=present+terminal-dec(net_debt)
    return {'enterprise_value':money(present+terminal),'equity_value':money(equity),'value_per_share':money(equity/dec(shares)),'terminal_weight_percent':money(terminal/(present+terminal)*100),'formula':'逐年现金流/(1+r)^t + 末期现金流×(1+g)/(r-g)/(1+r)^n - 净债务；再除以股数','assumption_note':'输入须同币种、同金额单位；折现率和永续增长为情景假设，不是预测。'}

def valuation_scenarios(calculation):
    item=calculation.get('inputs')
    if not item or item.get('eps') is None or dec(item['eps'])<=0:return []
    eps=dec(item['eps'])
    return [{'earnings_change_percent':str(change),'pe_multiple':str(multiple),'value_per_share':money(eps*(1+Decimal(change)/100)*multiple),'currency':item['currency'],'evidence_id':item['evidence_id'],'assumption':True,'note':'盈利变化与估值倍数为假设；未证明合理区间，不能作为目标价'} for change in (-20,0,20) for multiple in (10,20,30)]
