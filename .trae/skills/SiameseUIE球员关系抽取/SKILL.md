---
name: "SiameseUIE球员关系抽取"
description: "使用 SiameseUIE 对赛后已分词直播文本抽取球员攻防关系并落库。Invoke when 用户要求分析球员之间的攻防、助攻、防守、抢断、盖帽等关系时。"
---

# SiameseUIE球员关系抽取

## 适用场景
- 用户要求对 `nba_zhiboba_live_text_event` 中已经完成分词的文本做赛后语义分析
- 用户要求抽取球员之间的攻防关系、配合关系、防守关系
- 用户要求把关系抽取结果写入数据库并通过 Swagger 验证

## 核心能力
- 读取 `nba_zhiboba_live_text_event.segmented_text`
- 使用 SiameseUIE 模式抽取球员关系
- 结合球员别名表与主球员表，把别名统一为完整球员名称
- 将结果写入 `nba_zhiboba_player_relation`

## 默认输入
- 数据来源表：`nba_zhiboba_live_text_event`
- 过滤条件：
  - `saishi_id = 指定比赛ID`
  - `segmented_text IS NOT NULL`
  - `TRIM(segmented_text) <> ''`

## 默认抽取关系
- 进攻侧：
  - `assist_to`
  - `screen_for`
  - `attacks_against`
  - `scores_over`
- 防守侧：
  - `defends`
  - `contests_shot`
  - `forces_turnover`
  - `steals_from`
  - `blocks`
  - `fouls_on`

## 抽取思路
1. 读取比赛的已分词文本。
2. 将 `segmented_text` 中的 `\` 分隔符还原成连续文本，作为 SiameseUIE 输入。
3. 使用以下关系 schema 抽取：
   - `进攻球员 -> 防守球员 / 协作球员 / 进攻动作 / 结果 / 得分值`
   - `防守球员 -> 进攻球员 / 防守动作 / 结果`
4. 将抽取出来的球员名称通过：
   - `nba_players_name_data`
   - `player_alias_name_info`
   归一化为完整球员名称。
5. 生成标准关系记录并落库。

## 数据落库
- 目标表：`nba_zhiboba_player_relation`
- 核心字段：
  - `saishi_id`
  - `evidence_event_id`
  - `live_sid`
  - `relation_type`
  - `relation_side`
  - `subject_player_name`
  - `object_player_name`
  - `action_text`
  - `result_text`
  - `score_points`
  - `evidence_text`
  - `segmented_text`
  - `extractor_name`
  - `confidence`

## 推荐调用方式
- Swagger API：
  - `POST /api/v1/live-text/zhiboba/relations/extract?saishi_id={比赛ID}`

## 返回要求
- 返回比赛ID：
  - `saishi_id`
- 返回处理统计：
  - `events`
  - `relations`
  - `backend`
  - `model_name`
- 返回关系抽样：
  - `live_sid`
  - `relation_type`
  - `relation_side`
  - `subject_player_name`
  - `object_player_name`
  - `action_text`
  - `result_text`
  - `score_points`
  - `evidence_text`
  - `segmented_text`
  - `confidence`

## 注意事项
- 必须优先使用已完成分词的文本，不直接读取未分词原文作为主输入。
- 如果当前环境的 SiameseUIE 模型不可用，应返回 `backend=unavailable`，而不是伪造结果。
- 如果用户要求全量赛后分析，建议按 `saishi_id` 一场一场执行，避免一次性处理过多比赛。
