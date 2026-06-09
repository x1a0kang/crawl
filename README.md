# crawl

马拉松赛事离线采集流水线。它只生成待审核数据，不直接写入正式赛事库。

## 目标

- 从可信来源发现赛事线索（中国马拉松官方站、第一赛道公开 API、最酷公开列表）。
- 从报名平台公开页、官方入口和可访问详情页抽取字段。
- 只保留 MVP 范围内的半马 / 全马候选。
- 输出人工审核友好的 CSV / JSONL。

## 快速开始

从项目根目录 `/Users/ruikang/project/run` 执行：

```bash
# 默认抓近三年（运行当天向前 3 年）
python3 -m crawl.main all \
  --sources china-marathon,sport-china,zuicool \
  --out crawl/output/last-3-years \
  --last-years 3 \
  --max-pages 120 \
  --rendered-fetcher auto

# 也可以拆成两步：先发现、再抽取
python3 -m crawl.main discover --sources china-marathon,sport-china,zuicool --out crawl/output/last-3-years --last-years 3
python3 -m crawl.main extract --input crawl/output/last-3-years/leads.csv --out crawl/output/last-3-years
```

如果当前目录已经是 `crawl/`，也可以执行：

```bash
python3 main.py all --sources sport-china,zuicool --out output --no-fetch --last-years 3
```

显式日期范围仍可使用（覆盖 `--last-years`）：

```bash
python3 -m crawl.main all \
  --sources china-marathon,sport-china,zuicool \
  --out crawl/output/2026-01-01_2026-06-09 \
  --date-from 2026-01-01 \
  --date-to 2026-06-09 \
  --max-pages 120 \
  --rendered-fetcher auto
```

如果只想先跑列表发现、不抓每个详情页：

```bash
python3 -m crawl.main all \
  --sources china-marathon,sport-china,zuicool \
  --out crawl/output/2026-01-01_2026-06-09 \
  --date-from 2026-01-01 \
  --date-to 2026-06-09 \
  --no-fetch
```

如果本机没有 `firecrawl` CLI、又想暂时跳过中国马拉松官方站：

```bash
python3 -m crawl.main all \
  --sources sport-china,zuicool \
  --out crawl/output/last-3-years \
  --last-years 3 \
  --rendered-fetcher none
```

## CLI 标志

| 标志 | 说明 |
| --- | --- |
| `--sources` | 逗号分隔的来源名（默认 `china-marathon,sport-china,zuicool`）。 |
| `--out` | 输出目录。 |
| `--date-from` / `--date-to` | 显式事件日期窗口，覆盖 `--last-years`。 |
| `--last-years N` | 未传日期时按运行当天向前推 N 年（默认 3）。 |
| `--max-pages N` | 每个源允许抓取的最大分页数（默认 120）。 |
| `--rendered-fetcher auto\|firecrawl\|none` | 渲染抓取器选择；中国马拉松官方站需要 JS 渲染时使用。 |
| `--no-fetch` | 跳过详情页抓取（只保留列表阶段的字段）。 |
| `--manual-seeds` | 手工种子 CSV 路径（仅 `--sources manual`）。 |

## 输出文件

- `output/leads.csv`：赛事线索。
- `output/candidates.csv`：待审核赛事候选。
- `output/evidence.jsonl`：字段级来源证据和人工追查查询词。

CSV 使用 `utf-8-sig` 写出，方便表格软件直接打开。

## 来源策略

- `china-marathon`：中国马拉松官方网站 `https://www.runchina.org.cn/#/race`，需要通过 `firecrawl` 渲染后解析表格（开赛时间、比赛名称、赛事等级、比赛地点、比赛项目）；解析后按 `date_from` 早停并去除 10 公里、健康跑、欢乐跑等非半马/全马项目。`marathon.org.cn` 暂不作为权威源。
- `sport-china`：第一赛道公开 JSON 接口 `https://api.sport-china.cn/officialApi/getRaces?page=N`，按 `raceId` 拼接详情 URL `https://app.sport-china.cn/race/#/offline/detail/{raceId}`。
- `zuicool`：最酷公开列表分页 `events?type=run&page=N&per-page=100`、`events/newreg?page=N&per-page=100`、`events/reg?page=N&per-page=100`，解析 `/event/{id}` 卡片，按 (url, name, date) 去重。
- `manual`：从 `seeds.csv` 导入手工线索。
- `mali` / `nowrun`：占位连接器，暂不做小程序或深度抓取。

## 过滤与输出

- 只保留半马 / 全马 / 马拉松候选。
- 排除越野、跑山、健康跑、欢乐跑、亲子跑、线上赛、铁三、垂直马拉松等。
- 中国马拉松官网作为最高置信度线索源；第一赛道、最酷作为报名平台补充证据。
- 输出仍为 `leads.csv`、`candidates.csv`、`evidence.jsonl`，默认 `pending_review`。

## 手动种子 CSV

使用 `--sources manual --manual-seeds seeds.csv` 导入。字段建议：

```csv
source_name,source_url,raw_title,event_name,event_date,province,city,event_items
manual,https://example.com,2026某某半程马拉松,2026某某半程马拉松,2026-04-12,江苏,南京,半马
```

## 依赖

核心实现只使用 Python 标准库；`rendered-fetcher=firecrawl` 需要本机安装并登录 `firecrawl` CLI；`requirements.txt` 中列出的是后续增强依赖。
