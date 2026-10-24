# 装机价格雷达 📡

电脑配件价格看板（全云端，GitHub Actions 每小时自动更新）：

**https://sgbd0.github.io/pc-price-tracker/**

- 覆盖 ZOL 十大品类 381 款在售配件（CPU/显卡/内存/主板/固态/机械硬盘/电源/机箱/散热器/显示器）
- 双渠道价格：ZOL 参考报价 + 京东渠道价（CPU/显卡/主板）
- 30 天历史价格与趋势：实时记录 + Internet Archive 快照回填
- 🥬 白菜价（记录期最低价）与买入建议，Qwen2.5-3B 模型每日自动生成观察与推荐
- 全网累计访问计数、今日分时、涨跌榜、收藏、CSV 导出

数据与页面完全由 `.github/workflows/daily-update.yml` 在 GitHub 服务器上自动维护，
不依赖任何本地设备。历史数据在 `data/prices.csv`。
