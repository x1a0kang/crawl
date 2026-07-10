# crawl

马拉松赛事数据采集工具集。包含两个独立脚本：

1. **crawl_china_marathon.py** — 从中国马拉松官网 search 分页接口爬取赛事列表，直接输出 events.csv
2. **doubao_web_search/** — 调用火山方舟豆包联网搜索，补充赛事详情信息

---

## 1. 中国马拉松官网爬虫

从 `runchina.org.cn` 官方 search 分页接口直接抓取赛事数据，输出 events.csv。

### 启动命令

从项目根目录 `/Users/ruikang/project/run` 执行：

```bash
# 默认爬最近3年（运行当天向前3年），输出到 crawl/output/events.csv
python3 crawl/crawl_china_marathon.py

# 指定日期范围
python3 crawl/crawl_china_marathon.py 2025-01-01 2025-12-31

# 指定日期范围 + 自定义输出路径
python3 crawl/crawl_china_marathon.py 2025-01-01 2025-12-31 crawl/output/2025-events.csv
```

如果当前目录已经是 `crawl/`：

```bash
python3 crawl_china_marathon.py 2025-01-01 2025-12-31
```

### 输出格式

输出 CSV 列：`name, province, city, district, event_date, item_types, level_label, organizer, status`

- 仅使用标准库，无需安装额外依赖
- 只保留全马、半马、十公里赛事
- 排除越野、跑山、线上赛、铁三、垂直马拉松
- CSV 使用 `utf-8-sig` 编码，表格软件可直接打开

---

## 2. 豆包联网搜索

调用火山方舟豆包模型的联网搜索能力，根据赛事名称联网搜索公开信息并输出结构化 JSON。

### 安装依赖

```bash
pip3 install volcenginesdkarkruntime
```

### 启动命令

从项目根目录执行：

```bash
# 对 events.csv 中的赛事做联网搜索，输出 JSON
python3 crawl/doubao_web_search/doubao_web_search.py crawl/output/events.csv crawl/output/doubao_result.json
```

如果当前目录已经是 `crawl/`：

```bash
python3 doubao_web_search/doubao_web_search.py output/events.csv output/doubao_result.json
```

### 简单 Demo

```bash
python3 crawl/doubao_web_search/demo.py
```

### 说明

- 输入为 CSV 文件，读取赛事名称、日期、省市区等字段
- 模型固定使用 `doubao-seed-2-1-pro-260628`，启用 `web_search` 工具
- 输出为 JSON 格式，包含赛事详情、项目信息等结构化数据
- API Key 已在代码中配置，无需额外设置
