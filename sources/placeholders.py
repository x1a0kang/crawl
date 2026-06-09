from __future__ import annotations

from typing import Iterable

from crawl.models import Lead, SourceConnector


class MaliSource(SourceConnector):
    name = "mali"

    def discover(self) -> Iterable[Lead]:
        # 马历第一版只保留连接器占位；小程序/封闭页面线索先通过 manual seeds 导入。
        return []


class NowRunSource(SourceConnector):
    name = "nowrun"

    def discover(self) -> Iterable[Lead]:
        # 闹跑第一版只保留连接器占位；批量自动化待后续基于公开网页细化。
        return []

