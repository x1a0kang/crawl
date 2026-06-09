# crawl

马拉松赛事离线采集流水线。它只生成待审核数据，不直接写入正式赛事库。

## 目标

- 从可信来源发现赛事线索。
- 从报名平台公开页、官方入口和可访问详情页抽取字段。
- 只保留 MVP 范围内的半马 / 全马候选。
- 输出人工审核友好的 CSV / JSONL。

## 快速开始

从项目根目录 `/Users/ruikang/project/run` 执行：

```bash
python3 -m crawl.main discover --sources china-marathon,sport-china,zuicool --out crawl/output
python3 -m crawl.main extract --input crawl/output/leads.csv --out crawl/output
python3 -m crawl.main all --sources china-marathon,sport-china,zuicool --out crawl/output
```

如果当前目录已经是 `crawl/`，也可以执行：

```bash
python3 main.py all --sources sport-china,zuicool --out output --no-fetch
```

如果只想验证数据契约，不抓详情页：

```bash
python3 -m crawl.main all --sources sport-china,zuicool --out crawl/output --no-fetch
```

抓取指定赛事日期范围，例如 2026-01-01 到 2026-06-09：

```bash
python3 -m crawl.main all \
  --sources china-marathon,sport-china,zuicool \
  --out crawl/output/2026-01-01_2026-06-09 \
  --date-from 2026-01-01 \
  --date-to 2026-06-09
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

## 输出文件

- `output/leads.csv`：赛事线索。
- `output/candidates.csv`：待审核赛事候选。
- `output/evidence.jsonl`：字段级来源证据和人工追查查询词。

CSV 使用 `utf-8-sig` 写出，方便表格软件直接打开。

## 来源策略

第一版内置：

- `china-marathon`：中国马拉松相关页面，作为权威基础线索。
- `sport-china`：第一赛道公开赛事列表。
- `zuicool`：最酷公开赛事和报名页。
- `manual`：从 `seeds.csv` 导入手工线索。
- `mali` / `nowrun`：占位连接器，暂不做小程序或深度抓取。

## 手动种子 CSV

使用 `--sources manual --manual-seeds seeds.csv` 导入。字段建议：

```csv
source_name,source_url,raw_title,event_name,event_date,province,city,event_items
manual,https://example.com,2026某某半程马拉松,2026某某半程马拉松,2026-04-12,江苏,南京,半马
```

## 依赖

当前核心实现只使用 Python 标准库，`requirements.txt` 中列出的是后续增强依赖。
