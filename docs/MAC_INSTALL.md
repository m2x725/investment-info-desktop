# Mac 测试版

适用于 Apple Silicon（M 系列）Mac，包含运行依赖，解压后将 InvestmentInfo.app 拖入应用程序文件夹。

本版本为测试预览，未取得 Apple Developer ID 签名与公证。macOS 可能阻止首次打开，请核对 GitHub 发布页及 SHA256；不要全局关闭 Gatekeeper。

启动前先退出正在运行的开发版，本机 8765 端口不能同时运行两份程序。点击窗口关闭会退出后台，当前 Mac 版没有 Windows 托盘和登录启动功能。

数据目录：~/Library/Application Support/InvestmentInfo。安装包不包含账户数据或密钥，不自动导入开发版数据。当前 Mac 版密钥仅保存在内存，退出后需重新填写。

测试顺序：打开应用 → 维护设置填写 Kimi 密钥、输入单价和输出单价并保存 → 搜索公司加入自选 → 收集资料 → 公司研究。若收集长时间不完成，请记录耗时并查看运行记录；本版本尚未修复 Windows 上观察到的收集耗时问题。请勿反复提交任务或付费重试。
