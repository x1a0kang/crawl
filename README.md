# crawl

马拉松赛事离线采集流水线。它只生成待审核数据，不直接写入正式赛事库。

## 目标

- 从中国马拉松官方站发现赛事线索。
- 从中国马拉松详情 API 抽取基础详情字段。
- 只保留 MVP 范围内的全马 / 半马 / 十公里赛事候选。
- 输出可直接导入 `events` 表的 CSV，以及字段级证据 JSONL。

## 快速开始

从项目根目录 `/Users/ruikang/project/run` 执行：

```bash
# 默认抓近三年（运行当天向前 3 年）
python3 -m crawl.main all \
  --out crawl/output/last-3-years \
  --last-years 3 \
  --max-pages 120

# 也可以拆成两步：先发现、再抽取
python3 -m crawl.main discover --out crawl/output/last-3-years --last-years 3
python3 -m crawl.main extract --input crawl/output/last-3-years/leads.csv --out crawl/output/last-3-years
```

如果当前目录已经是 `crawl/`，也可以执行：

```bash
python3 main.py all --out output --last-years 3
```

显式日期范围仍可使用（覆盖 `--last-years`）：

```bash
python3 -m crawl.main all \
  --out crawl/output/2026-01-01_2026-06-09 \
  --date-from 2026-01-01 \
  --date-to 2026-06-09 \
  --max-pages 120
```

## CLI 标志

| 标志 | 说明 |
| --- | --- |
| `--sources` | 逗号分隔的来源名（默认 `china-marathon`）。线上 lead 只使用 `china-marathon`；`sport-china`、`zuicool` 会被忽略。 |
| `--out` | 输出目录。 |
| `--date-from` / `--date-to` | 显式事件日期窗口，覆盖 `--last-years`。 |
| `--last-years N` | 未传日期时按运行当天向前推 N 年（默认 3）。 |
| `--max-pages N` | 每个源允许抓取的最大分页数（默认 120）。 |
| `--manual-seeds` | 手工种子 CSV 路径（仅 `--sources manual`）。 |

## 输出文件

- `output/leads.csv`：赛事线索。
- `output/events.csv`：可直接导入 `events` 表的赛事候选，不包含 `id`、`created_at`、`updated_at`。
- `output/evidence.jsonl`：字段级来源证据。

CSV 使用 `utf-8-sig` 写出，方便表格软件直接打开。

## 来源策略

- `china-marathon`：中国马拉松官方网站 `https://www.runchina.org.cn/#/race/v/list`，通过官方接口 `searchCompetitionMls` 按 `pageNo` 翻页获取列表，再用 `searchById` 获取基础详情；解析后按 `date_from` 早停并保留全马、半马、十公里项目。`marathon.org.cn` 暂不作为权威源。
- 中国马拉松 lead 的 `source_url` 是内部来源标识，格式如 `china-marathon:race_id=1000388111;page=1`；它不是网页 URL，详情抽取会用其中的 `race_id` 调用 POST 接口。
- `sport-china`：第一赛道连接器仍保留在代码中用于调试，但不再参与 `leads.csv` 生成。
- `zuicool`：最酷连接器仍保留在代码中用于调试，但不再参与 `leads.csv` 生成。
- `manual`：从 `seeds.csv` 导入手工线索。
- `mali` / `nowrun`：占位连接器，暂不做小程序或深度抓取。

## 过滤与输出

- 只保留全马、半马、十公里候选，输出 `item_types` 为 JSON 数组字面量，例如 `["full_marathon","half_marathon","ten_km"]`。
- 硬排除越野、跑山、线上赛、线上跑、铁三、垂直马拉松；健康跑、欢乐跑、亲子跑只有在没有识别到全马/半马/十公里时排除。
- 赛事等级清洗：`A`/`B`/`C` 单独写为 `A类`/`B类`/`C类`；`A 属地办赛`/`B 属地办赛`/`C 属地办赛` 等带"属地办赛"描述的，统一去掉后缀保留等级字母并加"类"后缀。
- 中国马拉松官网作为唯一线上线索源；第一赛道、最酷不再作为 lead 来源。
- 输出为 `leads.csv`、`events.csv`、`evidence.jsonl`，自动生成数据默认 `status=draft`。

## 导入 events 表

十公里项目需要先执行迁移：

```sql
\i migrations/001_allow_ten_kilometer_item_type.sql
```
（该迁移同时把约束中的 `ten_kilometer` 改为 `ten_km`，与 CSV 输出一致。）

导入 `events.csv`：

```sql
\copy events(name,province,city,district,event_date,item_types,start_time,registration_start_at,registration_end_at,lottery_result_date,registration_status,race_status,level_label,certification_label,organizer,start_point,finish_point,packet_pickup_location,address_text,official_site_url,description,status)
from 'output/events.csv'
with (format csv, header true, null '');
```

## 手动种子 CSV

使用 `--sources manual --manual-seeds seeds.csv` 导入。字段建议：

```csv
source_name,source_url,raw_title,event_name,event_date,province,city,event_items
manual,https://example.com,2026某某半程马拉松,2026某某半程马拉松,2026-04-12,江苏,南京,半马
```

## 依赖

核心实现只使用 Python 标准库；当前主流程不依赖第三方网页搜索或页面抓取工具。
