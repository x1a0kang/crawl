"""Demo Doubao web search call with timing logs.

Author: juruikang
Date: 2026-07-07
"""

import logging
import time

from volcenginesdkarkruntime import Ark


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

client = Ark(
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    api_key='68bfba1d-95d1-4183-8f83-da63f989fe0b',
)

prompt = "你是马拉松赛事数据整理助手。请根据下面给出的赛事名称、日期、省市区，联网搜索该赛事今年对应届次的公开信息，并输出一个可用于赛事导入的JSON对象。赛事定位信息：{\"rowNumber\":2,\"name\":\"2026杭州女子半程马拉松\",\"eventDate\":\"2026-04-26\",\"province\":\"浙江省\",\"city\":\"杭州市\",\"district\":\"拱墅区\"}必须遵守：搜索中没有明确获取到的字段禁止猜测，值用null表示，往年的赛事信息如规模，起终点等信息禁止填充到今年的赛事，直接输出json，禁止输出除json外的任何内容输出JSON结构要求：-顶层必须是一个对象，包含event和items两个字段，不要输出数组。-event.name使用赛事名称，event.province/event.city/event.district使用给定行政区，event.eventDate使用yyyy-MM-dd。-event.startTime使用HH:mm:ss或null。-event.registrationStartAt和event.registrationEndAt使用yyyy-MM-ddHH:mm:ss或null。-event.registrationMode只能是direct、lottery或null。-event.lotteryResultDate使用yyyy-MM-dd或null。-event.levelLabel只能是A、B、C或null。-event.certificationLabel只能是标牌、精英标、金标、白金标或null。-event.registrationChannel如能确认，格式为渠道类型-渠道名称，多个渠道用英文逗号分隔；不能确认则为null。-event.seriesKey尽量生成稳定英文小写下划线标识；不能确认同一赛事系列时为null。-event.status固定为published。-items至少包含一个项目；itemType只能是full_marathon、half_marathon、ten_km。-起点startPoint和终点finishPoint必须放在items[]中，不要放在event中。-distanceKm、feeAmount、quotaCount、packetPickupLocation无明确来源时使用null。-没有可靠来源时不要生成registeredCount字段。"

logging.info("Starting Doubao web search demo request")
logging.info("Prompt length: %s", len(prompt))
request_started_at = time.perf_counter()

response = client.responses.create(
    model="doubao-seed-2-1-pro-260628",
    input=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": prompt
                },
            ],
        }
    ], tools=[{
        "type": "web_search",
        "max_keyword": 3
    }]
)

elapsed_seconds = time.perf_counter() - request_started_at
logging.info("Doubao web search demo request completed in %.3f seconds", elapsed_seconds)
logging.info("Response id: %s", getattr(response, "id", None))
logging.info("Response status: %s", getattr(response, "status", None))
logging.info("Response usage: %s", getattr(response, "usage", None))

print(response)
