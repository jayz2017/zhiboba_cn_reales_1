---
name: "球队球员"
description: "获取直播吧球队主页的球员列表数据，提取球员ID、球衣号码、薪资、位置等信息，优先写入 zhiboba_* 字段，并落库至 nba_players_name_data 表。当用户要求拉取球队信息或球员信息时调用。"
---

# 球队球员（直播吧 NBA）

## 适用场景（何时调用）
- 用户要求获取/同步“直播吧（zhibo8）球队主页下的球员列表数据”并写入 MySQL
- 提取指定球队下的所有球员基本信息（如 `zhiboba_player_id`、球衣号码、当赛季薪资、位置等）并落库
- 用户要求自动从 `nba_teams_name_data` 中读取全部 `team_type='NBA'` 的球队，再循环抓取每支球队球员信息

## 请求信息

### URL
- 基础 URL：`https://data.zhibo8.cc/manage/public/app.php`
- 球员详情 URL：`https://data.zhibo8.cc/manage/public/app.php?_url=/nba_v2_player/player&playerId=215757`


### Method
- `GET`

### Params（必须）
- `_url`：`/nba_v2/team`
- `random`：随机浮点数（例如 `0.2616649554770061`）
- `teamId`：球队ID（例如老鹰队的 `6916`）

### 球员详情 Params（自动补充 player_code）
- `_url`：`/nba_v2_player/player`
- `playerId`：球员ID（例如 `215757`）

### Headers（建议）
- `accept: application/json, text/plain, */*`
- `referer: https://data.zhibo8.cc/nbaData/team/`
- `user-agent: (保持浏览器 UA)`

## 返回结构解析

### 预期结构（示意）
```json
{
  "status": "1",
  "data": {
    "team": {
      "teamId": "6916",
      "teamName": "老鹰"
    },
    "player": {
      "info": {
        "list": [
          {
            "playerId": "215766",
            "姓名": "乔纳森·库明加",
            "位置": "前锋",
            "球号": "0",
            "当赛季薪资": "$23,799,569"
          }
        ]
      }
    }
  }
}
```

### 关键字段映射（优先落库 zhiboba 字段）
- **Team 层级 (`data.team`)**：
  - `teamId` → `team_id`
  - `teamName` → `team_name`
- **Player 层级 (`data.player.info.list`)**：
  - `playerId` → `zhiboba_player_id` (唯一键)
  - `姓名` 或 `球员` → `zhiboba_player_name`
  - 入库前需清洗球员名中的 `.`、空格和 `·`，统一替换为空字符后再写入 `nba_players_name_data`
  - `球号` → `zhiboba_jersey_number`
  - `位置` → `position_name`
  - 二次请求球员详情中的 `playerCode` → `player_code`
  - `当赛季薪资` → `player_salary`：需要去除 `$` 和 `,` 转为浮点数（例如 `$23,799,569` → `23799569.00`），如果是 `-` 则写入 `NULL`。

## MySQL 落库

### 表不存在先创建
- 表名：`nba_players_name_data`

### 幂等策略
- 唯一键：`zhiboba_player_id`
- 写入：`INSERT ... ON DUPLICATE KEY UPDATE`

## 自动全量同步模式
- 数据来源表：`nba_teams_name_data`
- 过滤条件：`team_type='NBA'`
- 循环字段：`zhiboba_team_id`
- 执行方式：
  - 先查询全部 NBA 球队
  - 再逐条取出 `zhiboba_team_id`
  - 复用球队球员抓取接口 `/_url=/nba_v2/team`
  - 对每个球员继续补充详情接口中的 `playerCode`
  - 最终统一写入 `nba_players_name_data`
- 适合指令：
  - `同步全部 NBA 球队球员`
  - `自动从球队表读取 NBA 球队并抓取球员`
  - `按 nba_teams_name_data 全量同步球员`

## 重同步规则
- 当用户明确要求“从头重新同步球员”时，先删除 `nba_players_name_data` 中的历史球员数据，再执行全量同步。
- 删除旧数据后，仍按 `nba_teams_name_data` 中 `team_type='NBA'` 的全部球队逐一抓取并重新落库。
- 新落库的 `zhiboba_player_name` 必须先应用姓名清洗规则：去掉 `.`、空格和 `·` 后再写入。
- 若用户只要求增量同步，则不要先删表数据，直接走普通 upsert。

## 执行步骤（顺序）
1. 构造请求参数，带上目标 `teamId`。
2. 发起 GET 请求（headers + params）获取 JSON。
3. 解析 `data.team` 和 `data.player.info.list`，提取关键字段并清洗薪资数据。
4. 对每个球员使用 `playerId` 再请求一次球员详情接口，解析 `playerCode`。
5. 建表（若不存在）。
6. 若本次为“从头重新同步”，先清空 `nba_players_name_data` 历史数据。
7. 逐条 upsert 写入 MySQL 表 `nba_players_name_data`，包含 `player_code`。

## 可直接调用的 API
- 单球队同步：
  - `POST /api/v1/team/zhiboba/players/sync?team_id=6916`
- 全量 NBA 球队同步：
  - `POST /api/v1/team/zhiboba/players/sync/all`
  - 无需任何入参
