# 数据库设计

## MySQL 表设计game_list

### 1. 
保存比赛当前（当天）运行赛程信息的表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| home_team | VARCHAR(64) | 主队名称 |
| visit_team | VARCHAR(64) | 客队名称 |
| home_ls | INT | 主队联赛排名/轮次 |
| guest_ls | INT | 客队联赛排名/轮次 |
| guest_play_off_win | INT | 客队季后赛胜场 |
| guest_rank | INT | 客队排名 |
| guest_win_diff | DECIMAL(5,2) | 客队净胜分/差 |
| guest_win_or_filr | VARCHAR(32) | 客队胜/负状态 |
| guest_win_rate | DECIMAL(5,4) | 客队胜率 |
| guest_zone | INT | 客队所属赛区 |
| home_play_off_win | INT | 主队季后赛胜场 |
| home_rank | INT | 主队排名 |
| home_win_diff | DECIMAL(5,2) | 主队净胜分/差 |
| home_win_or_filr | VARCHAR(32) | 主队胜/负状态 |
| home_win_rate | DECIMAL(5,4) | 主队胜率 |
| home_zone | INT | 主队所属赛区 |
| period_cn | VARCHAR(64) | 节次/阶段名称 |
| create_date | TIMESTAMP | 数据创建日期 |
| end_date | DATE | 比赛结束日期 |
| sdate | DATE | 比赛开始日期 |
| start | TIME | 比赛开始时间 |
| time | VARCHAR(32) | 比赛具体时间(如进行到第几分钟) |
| season_type | VARCHAR(32) | 赛季类型（如常规赛/季后赛） |
| type | VARCHAR(32) | 比赛类型 |
| created_at | TIMESTAMP | 记录创建时间 |
| updated_at | TIMESTAMP | 记录更新时间 |

**索引建议**:
- `PRIMARY KEY (id)`
- `KEY idx_sdate (sdate)`

---

### 2. nba_zhiboba_yj_gamelist
保存执行整个赛季的赛程信息的表（与预赛程同步对齐）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| saishi_id | VARCHAR(32) | 赛事唯一ID (直播吧saishi_id) |
| game_date | DATE | 比赛日期 (如 2025-06-26) |
| start_time | TIME | 比赛开始时间 (如 08:00:00) |
| home_team_id | VARCHAR(32) | 主队ID |
| guest_team_id | VARCHAR(32) | 客队ID |
| is_finish | TINYINT | 是否完赛 (0:未完赛, 1:已完赛) |
| event_name | VARCHAR(128) | 赛事名称 (如选秀大会、常规赛) |
| created_at | TIMESTAMP | 数据创建时间 |
| updated_at | TIMESTAMP | 数据更新时间 |

**索引建议**:
- `PRIMARY KEY (id)`
- `UNIQUE KEY uk_saishi_id (saishi_id)`
- `KEY idx_game_date (game_date)`
- `KEY idx_home_guest (home_team_id, guest_team_id)`

---

### 3. nba_players_name_data
保存采集球队所有球员的名称和编码、球员在场任职位置的信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| team_id | VARCHAR(32) | 球队ID |
| team_name | VARCHAR(50) | 球队名称 |
| player_id | VARCHAR(50) | nbastore 球员id (可为空) |
| zhiboba_player_id | VARCHAR(50) | 直播吧球员id |
| hu_pu_player_id | VARCHAR(50) | 虎扑网站球员id |
| en_player_name | VARCHAR(128) | 球员英文名 |
| nba_player_name | VARCHAR(128) | NBA官方球员名 |
| zhiboba_player_name | VARCHAR(128) | 直播吧球员名 |
| player_name_alias | VARCHAR(128) | 球员别名/昵称 |
| nba_jersey_number | VARCHAR(16) | NBA官方球衣号码 |
| zhiboba_jersey_number | VARCHAR(16) | 直播吧球衣号码 |
| player_code | VARCHAR(50) | 球员编码 |
| player_salary | DECIMAL(15,2) | 球员薪资 (美元) |
| position_name | VARCHAR(64) | 场上位置 |
| created_at | TIMESTAMP | 数据创建时间 |
| updated_at | TIMESTAMP | 数据更新时间 |

**索引建议**:
- `PRIMARY KEY (id)`
- `UNIQUE KEY uk_zhiboba_player_id (zhiboba_player_id)`
- `UNIQUE KEY uk_player_id (player_id)`
- `KEY idx_team_id (team_id)`

---

### 4. nba_teams_name_data
保存球队名称和编码的信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| team_id | VARCHAR(32) | 球队ID (官方/全局) |
| zhiboba_team_id | VARCHAR(32) | 直播吧球队ID |
| team_name | VARCHAR(64) | 球队名称 |
| team_code | VARCHAR(32) | 球队编码 (如 LAL, GSW) |
| team_color | VARCHAR(16) | 球队代表色 (如 #FFFFFF) |
| icon_url | VARCHAR(512) | 球队图标URL |
| player_marker | VARCHAR(512) | 球员标识/标记图 |
| team_type | VARCHAR(32) | 球队所属赛区 (如 East/West) |
| total_salary | DECIMAL(15,2) | 球队总薪资 (美元) |
| out_salary | DECIMAL(15,2) | 外部薪资/离队球员薪资 |
| created_at | TIMESTAMP | 数据创建时间 |
| updated_at | TIMESTAMP | 数据更新时间 |

**索引建议**:
- `PRIMARY KEY (id)`
- `UNIQUE KEY uk_team_id (team_id)`
- `UNIQUE KEY uk_team_code (team_code)`
- `KEY idx_zhiboba_team_id (zhiboba_team_id)`

---

### 5. nba_player_alias (原 player_aliases)
保存球员标准名和别名映射。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| player_id | VARCHAR(50) | 关联的球员ID |
| original_name | VARCHAR(128) | 球员原名/英文名 |
| alias_name | VARCHAR(128) | 球员别名/绰号 |
| source_type | VARCHAR(32) | 别名来源类型 (如 hupu, zhibo8, user) |
| created_at | TIMESTAMP | 数据创建时间 |
| updated_at | TIMESTAMP | 数据更新时间 |

**索引建议**:
- `PRIMARY KEY (id)`
- `KEY idx_player_id (player_id)`
- `KEY idx_alias_name (alias_name)`

---

### 6. nba_zhiboba_live_text_token
保存比赛直播文本分词后的 token 数据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT UNSIGNED | 主键ID (自增) |
| live_sid | BIGINT UNSIGNED | 关联直播文本事件行ID |
| token | VARCHAR(128) | 分词后的单个词语 |
| created_at | TIMESTAMP | 数据创建时间 |

**表用途**:
- 保存 `live_text` 经过分词后的结果
- 一条直播文本会拆成多条 token 记录
- 用于关键词检索、词频统计、球员命中分析、动作词分析

**索引建议**:
- `PRIMARY KEY (id)`
- `UNIQUE KEY uk_live_sid_token (live_sid, token)`
- `KEY idx_token (token)`
