from crawl.sources.china_marathon import ChinaMarathonSource
from crawl.sources.manual_seed import ManualSeedSource
from crawl.sources.placeholders import MaliSource, NowRunSource
from crawl.sources.sport_china import SportChinaSource
from crawl.sources.zuicool import ZuicoolSource


SOURCE_REGISTRY = {
    "china-marathon": ChinaMarathonSource,
    "sport-china": SportChinaSource,
    "zuicool": ZuicoolSource,
    "manual": ManualSeedSource,
    "mali": MaliSource,
    "nowrun": NowRunSource,
}

