# Windows安装

1. 从 Releases 下载 InvestmentInfo-版本-Setup.exe。
2. 双击安装。首次安装缺少WebView2时，需要联网；运行时由Microsoft提供。
3. 双击桌面“投资信息台”。在维护设置填入Kimi API和可选微信推送配置。
4. 先验证一家公司研究、微信测试、定时日报，再导入持仓。
5. 关闭窗口后Windows继续在托盘运行；停止任务需从托盘选择“完全退出”。电脑关机/休眠时不能准点发送。

升级：先完全退出，运行新版安装程序。安装前备份数据库；数据在 %LOCALAPPDATA%\RetirementWealth，程序在 %LOCALAPPDATA%\Programs\InvestmentInfo。卸载只删除程序，不删除账户数据。

若Windows拦截未签名程序，请核实下载来自正确仓库，并由维护者核对SHA256SUMS.txt。不要关闭系统安全保护。当前预览版尚待Windows实机验收。
