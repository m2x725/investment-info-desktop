# 投资信息台

Windows 本地投资研究助手：公司研究、持仓核算、公开资料更新与微信提醒。独立桌面窗口，不执行交易。

## 下载与安装

在 Releases 下载 `InvestmentInfo-版本-Setup.exe`，双击安装。支持 Windows 10/11 x64，首次安装缺少 WebView2 时需要联网下载 Microsoft 运行时。无需安装 Python 或 Node.js。

当前为待实机验收的预览版。自动构建成功不代表真实研究质量、托盘与微信交付已经验收。详情见 docs/WINDOWS_INSTALL.md。

软件需要自行配置 Kimi API 与可选的 Server酱推送；API可能产生费用。数据库与密钥留在本机，研究时会调用配置的云端服务。行情可能延迟，结果用于辅助研究。

## 构建

Windows 安装 Python 3.12、Node.js、Inno Setup 6 后执行 scripts/Setup-Windows.ps1、scripts/Build-Windows.ps1、scripts/Build-Installer.ps1。

GitHub Actions 的 Windows installer 工作流可生成安装包与草稿 Release，完成实际验证后再发布。

第三方组件许可见 docs/OPEN_SOURCE_REVIEW.md，安装包附带依赖许可声明。本项目代码尚未指定开源许可证，公开可见不等于授予开源再分发许可。
