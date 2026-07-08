# 赛事导入 JSON 规则

> 本文件用于生成赛事导入 JSON，再由导入脚本拆分写入 `events`、`event_items`、`event_channels`、`event_images` 等表。
> 当前后端没有直接接收该 JSON 的公开接口。

## JSON 示例

接口路径：

```http
POST /api/events/import
Authorization: Bearer <token>
Content-Type: application/json
```

本地导入页面：

```bash
SPRING_PROFILES_ACTIVE=local mvn spring-boot:run
```

```text
http://localhost/import-events.html
```

该页面只在 `local` profile 下暴露。非 `local` 环境不会注册 `/import-events.html`，`POST /api/events/import` 也不会免登录。

请求体是赛事 JSON 数组：

```json
[
  {
    "event": {
      "name": "2026上海马拉松",
      "province": "上海",
      "city": "上海",
      "district": "黄浦区",
      "eventDate": "2026-11-29",
      "startTime": "07:00:00",
      "registrationStartAt": "2026-08-01 10:00:00",
      "registrationEndAt": "2026-08-15 18:00:00",
      "registrationMode": "lottery",
      "lotteryResultDate": "2026-09-01",
      "levelLabel": "A",
      "certificationLabel": "金标",
      "organizer": "上海市体育局",
      "registrationChannel": "官网,小程序",
      "packetPickupLocation": "上海世博展览馆",
      "description": "赛事简介",
      "seriesKey": "shanghai_marathon",
      "status": "published"
    },
    "items": [
      {
        "itemType": "full_marathon",
        "distanceKm": 42.195,
        "feeAmount": 200,
        "currency": "CNY",
        "quotaCount": 20000,
        "startPoint": "外滩金牛广场",
        "finishPoint": "徐汇滨江",
        "packetPickupLocation": null
      },
      {
        "itemType": "half_marathon",
        "distanceKm": 21.0975,
        "feeAmount": 180,
        "currency": "CNY",
        "quotaCount": 12000,
        "startPoint": "外滩金牛广场",
        "finishPoint": "东方体育中心",
        "packetPickupLocation": null
      }
    ]
  }
]
```

响应示例：

```json
{
  "total": 1,
  "createdCount": 1,
  "updatedCount": 0,
  "items": [
    {
      "eventId": "event-uuid",
      "name": "2026上海马拉松",
      "eventDate": "2026-11-29",
      "action": "created"
    }
  ]
}
```

## event 字段

| 字段 | 类型 / 格式 | 必填 | 含义                                                                     |
|---|---|---:|------------------------------------------------------------------------|
| `name` | string | 是 | 赛事名称                                                                   |
| `province` | string | 是 | 省级行政区，例如 `上海`、`浙江省`                                                    |
| `city` | string | 是 | 市级行政区                                                                  |
| `district` | string / null | 否 | 区县级行政区                                                                 |
| `eventDate` | `yyyy-MM-dd` | 是 | 比赛日期                                                                   |
| `startTime` | `HH:mm:ss` / null | 否 | 开赛时间                                                                   |
| `registrationStartAt` | `yyyy-MM-dd HH:mm:ss` / null | 否 | 报名开始时间，例如 `2026-08-01 10:00:00`                                        |
| `registrationEndAt` | `yyyy-MM-dd HH:mm:ss` / null | 否 | 报名截止时间，例如 `2026-08-15 18:00:00`                                        |
| `registrationMode` | `direct` / `lottery` | 否 | 报名方式：`direct` 直报，`lottery` 抽签                                          |
| `lotteryResultDate` | `yyyy-MM-dd` / null | 抽签赛事建议填 | 出签日期                                                                   |
| `levelLabel` | `A` / `B` / `C` / null | 否 | 赛事等级                                                                   |
| `certificationLabel` | `标牌` / `精英标` / `金标` / `白金标` / null | 否 | 认证标识                                                                   |
| `organizer` | string / null | 否 | 主办方                                                                    |
| `registrationChannel` | string / null | 否 | 报名渠道；渠道内容包含两部分，渠道类型-渠道名称，多个渠道用英文逗号分隔，如：公众号-上马网,小程序-汇赛通,APP-上马网,官网-上马网。 |
| `packetPickupLocation` | string / null | 否 | 赛事级统一领物地点；项目级未填时可作为 fallback                                           |
| `description` | string / null | 否 | 赛事简介                                                                   |
| `seriesKey` | string / null | 强烈建议填 | 赛事系列标识，用于关联同一赛事不同年份，例如 `shanghai_marathon`                             |
| `status` | `published` | 是 | 发布状态；当前前端只查询 `published` 赛事                                            |

## items 字段

每个赛事必须至少有一个项目。赛事起点和终点放在项目维度，不放在 `event` 里。

| 字段 | 类型 / 格式 | 必填 | 含义 |
|---|---|---:|---|
| `itemType` | `full_marathon` / `half_marathon` / `ten_km` | 是 | 项目类型：全马 / 半马 / 十公里 |
| `distanceKm` | number / null | 否 | 项目距离，例如 `42.195`、`21.0975`、`10` |
| `feeAmount` | number / null | 否 | 报名费，单位元 |
| `currency` | string / null | 否 | 币种，国内赛事建议 `CNY` |
| `quotaCount` | integer / null | 否 | 项目名额 |
| `registeredCount` | integer | 否 | 已报名人数；没有可靠数据时不要填该字段 |
| `startPoint` | string / null | 建议填 | 项目起点 |
| `finishPoint` | string / null | 建议填 | 项目终点 |
| `packetPickupLocation` | string / null | 否 | 项目级领物地点；为空时使用 `event.packetPickupLocation` |

## 生成规则

- 导入接口按 `event.name + event.eventDate` 判断是否已存在。
- 如果赛事已存在，会更新 `events` 主表，并整体替换该赛事的 `items / channels / images`。
- 如果批量列表中任意一条失败，整批导入回滚，已经写入的数据也不会保留。
- `registrationStartAt` 和 `registrationEndAt` 必须使用 `yyyy-MM-dd HH:mm:ss`
- 起点和终点必须放在 `items[]` 中。
- 已报名人数没有可靠来源时，不要生成 `registeredCount` 字段。
- `seriesKey` 尽量稳定，同一赛事不同年份使用相同值。
- `status` 默认生成 `published`，否则当前前端接口查不到赛事。
