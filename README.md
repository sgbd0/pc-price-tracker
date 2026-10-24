# 电脑配件价格日报 🖥️💰

每天自动抓取电脑配件价格（CPU / 显卡 / 内存 / 固态硬盘 / 主板 / 电源……），
生成一份带涨跌标记和走势图的本地报告，**全程不联网上传任何数据**。

> **不想让电脑一直开机？** 看 [DEPLOY.md](DEPLOY.md)——一键部署到 GitHub，
> 云端每天自动更新并发布固定公开网址，电脑关机也不影响。

内置一个**特别小的本地模型**（Qwen2.5-0.5B，约 400MB，CPU 就能跑，无需显卡）：

1. 页面改版导致规则识别不到价格时，由小模型从网页文本里**兜底识别价格**；
2. 每天用小模型给当日涨跌写一段**中文摘要**（显示在报告顶部 🤖）。

小模型缺失时自动退回纯规则模式，日常更新不受影响。

## 网页版看板（公开访问）

除每日报告外，还有一个**常驻网页看板**（统计卡片、可交互走势图、全部商品表格）：

- **本机/局域网访问**：`http://127.0.0.1:8787`（把 `config.json` 里 `web.bind` 改成
  `0.0.0.0` 并放行防火墙后，同一 WiFi 下的手机也能打开）
- **公网访问**：由 Cloudflare 免费隧道（无需账号）转发，当前地址显示在网页顶部
  徽章里，也可以在 `logs\tunnel.log` 最后一行找到。**电脑重启或隧道重连后地址会变**，
  以看板上显示的最新地址为准。想要固定域名：运行
  `cloudflared tunnel login` 后按提示创建命名隧道（免费），或把 `web\` 目录发布到
  GitHub Pages / 任意静态托管（看板会自动回退读取 `web\data.json` 静态数据）。

看板服务（`web_server.bat`）和公网隧道（`tunnel.bat`）已注册为开机自启任务
`PcPartsPriceWeb`、`PcPartsPriceTunnel`。网页服务是**只读**的，没有任何写入接口，
公网暴露的只是价格数据；价格更新仍由每天 09:00 的 `PcPartsPriceDaily` 在本机完成。

相关命令：

```bat
python tracker.py web-export   :: 手动导出网页数据(web/data.json)
python tracker.py serve        :: 前台启动看板服务(调试用)
```

## 快速开始

双击 **`setup.bat`** 一键完成：创建虚拟环境 → 安装小模型运行库 → 下载小模型 →
注册每天 09:00 的 Windows 计划任务 → 立即跑一次验证。

装好后每天 09:00 自动更新，双击 `data\report.html` 查看最新报告。

> 前提：电脑装有 Python 3.10+（本机已确认是 3.12），且能上网。

## 日常使用

| 命令 | 作用 |
| --- | --- |
| `python tracker.py` | 立即更新一次价格并生成报告 |
| `python tracker.py list` | 查看监控清单 |
| `python tracker.py add https://detail.zol.com.cn/vga/indexxxxx.shtml [名称]` | 添加监控商品（名称可省略，自动取页面标题） |
| `python tracker.py remove 序号或名称` | 移除监控商品 |
| `python tracker.py test <URL>` | 测试某页面能否识别出价格 |
| `python tracker.py report` | 只用已有数据重新生成报告 |
| `python tracker.py model-setup` | 重新下载小模型 |

监控清单保存在 `config.json`，默认已带 10 件主流配件（9800X3D、RTX 5060 Ti、
致态 TiPlus7100 等），可随意增删。在 ZOL 商品页复制地址栏链接即可添加；
大多数电商详情页也能识别（自动尝试 JSON-LD / itemprop / 货币符号等规则）。

## 文件说明

```
tracker.py           主程序（抓取 + 识别 + 存储 + 报告 + 小模型）
config.json          监控清单和小模型设置
setup.bat            一键安装 + 注册每天自动更新
run_daily.bat        计划任务每天调用的入口
uninstall_task.bat   取消每天自动更新
data\prices.csv      全部历史价格（Excel 可直接打开）
data\report.html     每日报告（涨跌 + 近14天走势图）
data\latest.json     最新一次抓取结果
models\              本地小模型（约400MB）
logs\daily.log       每日自动更新的运行日志
```

## 自定义

- **改更新时间**：以管理员运行
  `schtasks /Change /TN "PcPartsPriceDaily" /ST 10:30`
- **关闭小模型**：编辑 `config.json`，把 `model.enabled` 改为 `false`
- **关闭每日摘要**：把 `model.summary` 改为 `false`
- **换模型**：把任意 GGUF 模型放进 `models\`，改 `config.json` 里 `model.file` 的文件名
  （推荐保持 0.5B 级别，太大就失去"特别小"的意义了）
- **取消全部后台任务**：管理员运行
  `schtasks /Delete /F /TN "PcPartsPriceDaily" & schtasks /Delete /F /TN "PcPartsPriceWeb" & schtasks /Delete /F /TN "PcPartsPriceTunnel"`

## 数据来源与识别优先级

价格识别按顺序尝试：ZOL「参考报价」字段 → JSON-LD 结构化数据 →
itemprop/meta 标记 → 页面货币符号 → 本地小模型兜底。
来源以中关村在线(ZOL)参考报价为主，是渠道参考价，实际成交价以电商页面为准。
