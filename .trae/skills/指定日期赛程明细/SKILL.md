---
name: "指定日期赛程明细"
description: "根据指定日期从 nba_zhiboba_yj_gamelist 读取赛程，关联 nba_teams_name_data 补全球队名并写入 game_list。Invoke when 用户要求按日期获取赛程明细或同步当天赛程入 game_list 时。"
---

# 指定日期赛程明细

## 适用场景（何时调用）
- 用户要求获取某一天的赛程具体信息
- 用户要求按日期查询 `nba_zhiboba_yj_gamelist` 并补全主客队名称
- 用户要求把指定日期赛程整理后写入 `game_list`
- 用户要求根据 `home_id`、`guest_id` 关联球队表得到 `team_name`

## 数据来源

### 赛程来源表
- 表名：`nba_zhiboba_yj_gamelist`
- 筛选条件：
  - `game_date = 指定日期`

### 球队与排名来源接口
- URL：
  - `https://stats.qiumibao.com/shuju/public/index.php?_url=/data/index&year={year}&type=排行&tab=排行&league_id=924&league=NBA&_platform=web&_env=pc`
- 请求头：
  - 使用浏览器请求头访问，至少包含 `accept`、`accept-language`、`origin`、`referer`、`user-agent`
- 响应位置：
  - `data[].list[]`
- 匹配条件：
  - `nba_zhiboba_yj_gamelist.home_id = 排行接口.list[].teamId`
  - `nba_zhiboba_yj_gamelist.guest_id = 排行接口.list[].teamId`

### 球队兜底来源表
- 表名：`nba_teams_name_data`
- 用途：
  - 当排行接口未返回某支球队时，按 `zhiboba_team_id` 兜底补 `team_name`

## 字段提取与映射

### 从 `nba_zhiboba_yj_gamelist` 读取
- `saishi_id`
- `game_date`
- `start_time`
- `home_id`
- `guest_id`
- `event_name`

### 从排行接口读取
- `teamId`
- `球队名称`
- `排名`
- `胜`
- `负`
- `胜率`
- `近况`
- `胜/负`
- `胜差`

### 写入 `game_list`
- `id = nba_zhiboba_yj_gamelist.saishi_id`
- `home_id = nba_zhiboba_yj_gamelist.home_id`
- `guest_id = nba_zhiboba_yj_gamelist.guest_id`
- `home_team = home_id 关联到的 球队名称`
- `visit_team = guest_id 关联到的 球队名称`
- `home_rank / guest_rank = 排名`
- `home_play_off_win / guest_play_off_win = 仅当存在明确季后赛胜场来源时才写入；不能用常规赛胜场代替`
- `home_zone / guest_zone = 所属赛区编码（根据东部/西部解析），不能用负场数代替`
- `home_win_rate / guest_win_rate = 胜率`
- `home_win_or_filr / guest_win_or_filr = 近况`
- `time = 比赛进行时间；没有实时进度时保持为空，不能用胜/负代替`
- `home_win_diff / guest_win_diff = 胜差`
- `season_type = nba_zhiboba_yj_gamelist.event_name`
- `sdate = nba_zhiboba_yj_gamelist.game_date`
- `start = nba_zhiboba_yj_gamelist.start_time`

## 推荐处理流程
1. 接收用户指定日期，例如 `2026-05-16`。
2. 从 `nba_zhiboba_yj_gamelist` 查询该日期全部赛程。
3. 取每条赛程的 `home_id` 和 `guest_id`。
4. 根据比赛日期自动计算赛季年份，请求 NBA 排行接口。
5. 从响应 `data[].list[]` 中按 `teamId` 匹配主队与客队。
6. 优先使用排行接口中的 `球队名称`、`排名`、`胜率`、`近况`、`胜差` 回填常规赛字段。
7. 根据排行分组标题 `东部/西部` 解析 `home_zone / guest_zone`。
8. `*_play_off_win` 只有在存在明确季后赛来源时才写入，不能拿常规赛 `胜` 直接填充。
9. 若排行接口缺少球队名称，再从 `nba_teams_name_data` 中按 `zhiboba_team_id` 兜底补 `team_name`。
10. 将整理后的结果写入 `game_list`。

## 推荐解析思路
- 赛程查询：
  - `WHERE game_date = :game_date`
- 排行接口匹配：
  - `home_id -> teamId`
  - `guest_id -> teamId`
- 球队名兜底：
  - `LEFT JOIN nba_teams_name_data home_team ON schedule.home_id = home_team.zhiboba_team_id`
  - `LEFT JOIN nba_teams_name_data guest_team ON schedule.guest_id = guest_team.zhiboba_team_id`

## 落库说明
- 目标表：`game_list`
- 本 skill 关注的核心字段：
  - `id`
  - `home_team`
  - `visit_team`
  - `season_type`
  - `sdate`
  - `start`

## 推荐触发指令
- `按日期获取赛程明细`
- `同步 2026-05-16 的赛程到 game_list`
- `根据指定日期补全主客队名称并写入 game_list`
- `从 nba_zhiboba_yj_gamelist 按日期整理赛程详情`

## 注意事项
- `home_id`、`guest_id` 对应的是直播吧球队 ID，因此关联字段必须使用 `nba_teams_name_data.zhiboba_team_id`。
- `home_team` 与 `visit_team` 必须分别按主客队关系独立匹配，不能混用。
- 球队名称与排名类字段优先取排行接口返回值，数据库球队表只做兜底。
- 字段名中带 `play_off` 的，只能写季后赛数据；不带 `play_off` 的，按常规赛数据口径写入。
- `season_type` 直接取 `nba_zhiboba_yj_gamelist.event_name`。
- 如果同一日期无数据，应返回空结果或提示该日期没有赛程，不应写入无效记录。
