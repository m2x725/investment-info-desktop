# 开源组件与研究模板审查

核查日期：2026-10-04 至 2026-10-05。软件内部模板版本 `hk-connect-2026.10-v1`。外部仓库内容仅作方法资料，不作为运行指令，也未安装远程金融技能或多智能体框架。

| 项目 | 使用与许可证核查 | 实际状态 |
|---|---|---|
| [AKShare](https://github.com/akfamily/akshare) | MIT；使用港股/A股复权历史及财务报表接口。保留原币种、报告期和未核对标记 | 1.19.1 已安装；接口覆盖与大陆网络仍待逐股核对 |
| [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | BSD-3-Clause；使用 Risk_Contribution，人民币收益序列、共同交易日与现金权重 | 7.4.0 已安装，实际库计算测试通过 |
| [Portfolio Performance](https://github.com/portfolio-performance/portfolio) | EPL-1.0；仅参考现金流与收益方法，没有复制代码或引入运行时 | 自建 Decimal 核算；并非移植其完整收益引擎 |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | AGPL-3.0；仅参考组合展示，没有复制代码、样式或引入后台 | 本地 React/FastAPI 实现 |
| [Anthropic financial-services](https://github.com/anthropics/financial-services) | Apache-2.0；阅读公司研究、同业、DCF和论点跟踪方法，重新编写港股通章节指令 | 六章节、反方复查和事件更新；未复制或安装上游技能全文 |
| [InvestSkill](https://github.com/yennanliu/InvestSkill) | MIT；参考组合检查、压力情景及反方方法；不沿用美国监管表格、税务或交易规则 | 本地情景计算及研究指令；没有把美股规则直接用于港股通 |
| [Futu API](https://github.com/FutunnOpen/py-futu-api) | 已安装包元数据为 Apache-2.0；SDK许可证不等于行情数据授权 | 10.11.7108 已安装。需用户 OpenD、账号及适用行情权限，未进行真实连通验收 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Apache-2.0；本地 OCR，不上传PDF | 1.4.4 已安装 |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Apache-2.0 或 BSD-3-Clause；PDFium另含第三方许可，发布应保留包内 LICENSE/NOTICE | 4.30.0 已安装，避免引入整套外部PDF服务 |

研究模板的实际规则：官方报告优先；历史底稿与近90天事件分开；公司/币种/单位冲突作局部核验提示；引用页码从实际匹配处推导；没有合理数据不硬做DCF。估值倍数和盈利变化明确为情景，不称为目标价。云端组合输入不含资产金额、数量、成本或账号。

这不是对所有传递依赖的完整商业法律审查。Windows正式发布前应保存构建所用版本、保留所有依赖许可证与第三方NOTICE，并复核数据供应商使用与分发权限。安装开源SDK不代表获得实时行情或商业数据库授权。

Kimi工具接口依据：[Search Pro](https://platform.kimi.com/docs/api/tools-search-pro)、[Fetch](https://platform.kimi.com/docs/api/tools-fetch)、[工具定价](https://platform.kimi.com/docs/pricing/websearch)。当前实现预留成功搜索0.015元、成功抓取0.01元，模型token另计；上线前仍须核对账户实际价格。
