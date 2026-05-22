---
name: "球员别名"
description: "根据比赛日期和比赛ID抓取球员中文别名，写入 player_alias_name_info 并按 player_id+alias_name 去重。Invoke when 用户要求同步球员别名、球员中文别名或比赛球员别名时。"
---

# 球员别名（比赛球员中文别名）

## 适用场景（何时调用）
- 用户要求同步某场比赛涉及球员的中文别名
- 用户要求批量从 `nba_zhiboba_yj_gamelist` 读取比赛信息，再抓取球员别名
- 用户要求把 `player_id` 与中文别名写入 `player_alias_name_info`

## 数据来源

### 比赛来源表
- 表名：`nba_zhiboba_yj_gamelist`
- 取值字段：
  - `saishi_id`：比赛 ID
  - `game_date`：比赛日期

### 目标请求 URL
- 模板：
  - `https://dc4pc.qiumibao.com/dc/matchs/data/{game_date}/player_{saishi_id}.htm?get={random}`
- 示例：
  - `https://dc4pc.qiumibao.com/dc/matchs/data/2026-05-16/player_1977335.htm?get=0.3555433551491515`

### URL 参数说明
- `{game_date}`：来自 `nba_zhiboba_yj_gamelist.game_date`
- `{saishi_id}`：来自 `nba_zhiboba_yj_gamelist.saishi_id`
- `{random}`：随机浮点数，用于避免缓存

## 返回字段解析

### 关键字段
- `player_id`：球员 ID
- `player_name_cn`：球员中文别名

### 字段映射
- `player_id` -> `player_alias_name_info.player_id`
- `player_name_cn` -> `player_alias_name_info.alias_name`
- 固定写入 `player_alias_name_info.type='NBA'`

## MySQL 落库

### 目标表
- 表名：`player_alias_name_info`
- 默认类型：`type='NBA'`

### 唯一去重规则
- 唯一键：`player_id + alias_name`
- 要求：
  - 同一个 `player_id`
  - 同一个 `alias_name`
  - 只允许保留一条

### 推荐写入方式
- `INSERT IGNORE`
- 或 `INSERT ... ON DUPLICATE KEY UPDATE`

## 执行步骤（顺序）
1. 从 `nba_zhiboba_yj_gamelist` 查询比赛数据，读取 `saishi_id` 与 `game_date`。
2. 按 `{game_date}` 和 `{saishi_id}` 组装别名抓取 URL。
3. 请求接口并解析返回数据。
4. 提取每条记录中的 `player_id` 和 `player_name_cn`。
5. 清洗空值、重复值，并在写入时补齐 `type='NBA'`。
6. 写入 `player_alias_name_info`，并按 `player_id + alias_name` 做唯一去重。

## 适合指令
- `同步球员别名`
- `抓取比赛球员中文别名`
- `根据赛程表批量同步球员别名`
- `把 player_id 和 player_name_cn 写入 player_alias_name_info`

## 边界说明
- 本 skill 只负责“别名抓取 + 解析 + 去重落库”。
- 数据来源依赖 `nba_zhiboba_yj_gamelist` 中已经存在 `saishi_id` 和 `game_date`。
- 如果用户要求接口级调用，应再补一个专用 API，或转到 `API总调度` 统一管理。
