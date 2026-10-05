"""Conservative title rules: a reading priority, never an investment-impact verdict."""
import re

RULES = (
    ("监管与法律事项", r"立案|調查|调查|处罚|處罰|訴訟|诉讼|仲裁|退市|除牌|清盤|破产|破產"),
    ("业绩重大变化", r"业绩预告|业绩快报|盈利警告|盈利預警|盈警|盈利預告|profit warning|profit alert"),
    ("经营与偿债事项", r"违约|違約|债务逾期|債務|停产|停產|重大事故|资金占用|資金佔用"),
    ("资本及控制权事项", r"重大资产|重大資產|重组|重組|收购|收購|控制权|控制權|要约|要約|配股|供股|停牌|暂停买卖|暫停買賣"),
    ("股东与分红事项", r"减持|減持|增持|权益分派|權益分派|利润分配|利潤分配|派息|特别股息|特別股息"),
)


def disclosure_signal(title):
    for reason, pattern in RULES:
        if re.search(pattern, title, re.I):
            return "high", reason
    if re.search(r"年度报告|半年度报告|季度报告|年報|中期報告|业绩|業績|annual report|interim report|results", title, re.I):
        return "normal", "定期财报与业绩"
    return "normal", "新增披露"
