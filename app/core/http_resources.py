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

# Official NBA game-card schedule feed. The Java service used this endpoint to
# fetch one date of NBA.com game cards and persist gameId/team matchup data.
NBA_STORE_GAMECARD_FEED_URL = "https://core-api.nba.com/cp/api/v1.3/feeds/gamecardfeed"

NBA_CHINA_PBP_DETAILS_URL = "https://api.nba.cn/sib/v2/pbp/details"
NBA_CHINA_PLAYERS_LIST_URL = "https://api.nba.cn/sib/v2/players/list"

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


def build_nba_store_game_headers() -> dict[str, str]:
    return {
        "host": "core-api.nba.com",
        "origin": "https://www.nba.com",
        "accept-language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "accept": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "referer": "https://www.nba.com/",
        "Ocp-Apim-Subscription-Key": "747fa6900c6c4e89a58b81b72f36eb96",
    }


def build_nba_china_pbp_headers() -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "origin": "https://china.nba.cn",
        "referer": "https://china.nba.cn/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
        ),
        "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
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
    if host == "core-api.nba.com":
        return build_nba_store_game_headers()
    if host == "api.nba.cn":
        return build_nba_china_pbp_headers()
    return {}
