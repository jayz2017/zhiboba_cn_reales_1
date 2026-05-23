from __future__ import annotations

from urllib.parse import urlparse

# 通用浏览器请求头中的 User-Agent，避免采集接口被轻易识别为脚本请求。
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
)

# 通用 Accept / Language 头，适用于项目中的 JSON / 文本抓取接口。
COMMON_ACCEPT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": DEFAULT_BROWSER_USER_AGENT,
}

# 直播文本分页抓取基础地址，用于抓取比赛逐条直播事件。
QIUMIBAO_LIVETEXT_BASE_URL = "https://dingshi2.qiumibao.com/livetext/data/cache/livetext"

# 球员别名抓取基础地址，用于按比赛日期 + 比赛 ID 获取中文别名。
QIUMIBAO_PLAYER_ALIAS_BASE_URL = "https://dc4pc.qiumibao.com/dc/matchs/data"

# 赛程与季后赛公共数据接口，用于拉取 NBA 常规赛 / 季后赛赛程。
QIUMIBAO_STATS_API_URL = "https://stats.qiumibao.com/shuju/public/index.php"

# NBA 排行榜接口，同样走 stats.qiumibao.com，用于按 teamId 取球队名、排名、胜负、胜率、近况。
QIUMIBAO_TEAM_RANKING_API_URL = QIUMIBAO_STATS_API_URL

# 球队 / 球员详情公共接口，用于抓取球队球员列表与球员详情 playerCode。
ZHIBO8_TEAM_DATA_API_URL = "https://data.zhibo8.cc/manage/public/app.php"


def build_qiumibao_headers(
    *,
    referer: str = "https://www.qiumibao.com/",
    origin: str = "https://www.qiumibao.com",
) -> dict[str, str]:
    return {**COMMON_ACCEPT_HEADERS, "origin": origin, "referer": referer}


def build_zhibo8_data_headers(
    *,
    referer: str = "https://data.zhibo8.cc/",
    origin: str = "https://data.zhibo8.cc",
) -> dict[str, str]:
    return {**COMMON_ACCEPT_HEADERS, "origin": origin, "referer": referer}


def build_zhibo8_mobile_headers() -> dict[str, str]:
    return {
        **COMMON_ACCEPT_HEADERS,
        "origin": "https://m.zhibo8.com",
        "referer": "https://m.zhibo8.com/",
    }


# 别名：直接代理到 build_qiumibao_headers()
def build_livetext_headers() -> dict[str, str]:
    return build_qiumibao_headers()


# 别名：直接代理到 build_qiumibao_headers()
def build_player_alias_headers() -> dict[str, str]:
    return build_qiumibao_headers()


def build_schedule_headers() -> dict[str, str]:
    return build_zhibo8_data_headers()


def build_team_ranking_headers() -> dict[str, str]:
    return {
        **build_zhibo8_data_headers(),
        "priority": "u=1, i",
        "sec-ch-ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
    }


def build_playoffs_headers() -> dict[str, str]:
    return build_zhibo8_mobile_headers()


def build_team_player_headers() -> dict[str, str]:
    return build_zhibo8_data_headers(referer="https://data.zhibo8.cc/nbaData/team/")


def get_default_headers_for_url(url: str) -> dict[str, str]:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("qiumibao.com"):
        return build_qiumibao_headers()
    if host.endswith("zhibo8.cc"):
        return build_zhibo8_data_headers()
    if host.endswith("zhibo8.com"):
        return {
            **COMMON_ACCEPT_HEADERS,
            "origin": "https://www.zhibo8.com",
            "referer": "https://www.zhibo8.com/",
        }
    return {}
