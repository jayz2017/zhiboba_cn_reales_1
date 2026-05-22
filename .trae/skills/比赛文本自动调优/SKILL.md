---
name: "比赛文本自动调优"
description: "从 game_list 依次选择比赛，自动执行直播文本抓取、分词、分词结果检查与过滤规则调优。Invoke when 用户要求按比赛顺序批量跑文本抓取分词并根据结果自动调规则时。"
---

# 比赛文本自动调优

## 适用场景（何时调用）
- 用户要求从 `game_list` 自动取比赛，不手工传 `saishi_id`
- 用户要求按顺序执行“比赛文本抓取 + 直播文本分词”
- 用户要求读取分词结果后，继续调整过滤条件、清洗规则或跳过规则
- 用户要求做“抓取 -> 分词 -> 观察结果 -> 调规则 -> 再跑”的闭环

## 核心职责
- 从 `game_list` 表中依次读取一条比赛数据
- 提取比赛 `id` 作为 `saishi_id`
- 先执行 `比赛文本抓取`
- 再执行 `直播文本分词`
- 再执行 `文本分词规格校验`
- 自动抽样读取分词结果
- 根据分词结果中的噪声文本、无效阶段、括号提示、口语助词等内容，调整 `nba_zhiboba_live_text_filter_rule`

## 默认选择规则
- 数据来源表：`game_list`
- 比赛 ID 字段：`id`
- 默认按以下顺序依次取一条：
  - 优先选择还没有直播文本事件数据的比赛
  - 如无法区分是否已跑过，则按 `id ASC` 或比赛时间顺序取最早的一条
- 每次只处理一场，避免把多场结果混在一起

## 推荐执行链路
1. 从 `game_list` 读取一条比赛数据。
2. 提取 `game_list.id -> saishi_id`。
3. 调用 `比赛文本抓取`：
   - `POST /api/v1/live-text/zhiboba/fetch?saishi_id={id}`
4. 调用 `直播文本分词`：
   - `POST /api/v1/live-text/zhiboba/sync?saishi_id={id}`
5. 调用 `文本分词规格校验`：
   - 校验 `line_skip + exact/contains` 规则是否真的落实到抓取后文本与 `segmented_text`
6. 如果规格校验通过：
   - 本轮停止，不再继续自动调优
7. 如果规格校验不通过：
   - 继续观察是否存在需要继续调优的噪声
   - 仅当本轮确实新增了规则或有实际变更时才继续重跑
8. 读取本场分词结果：
   - `nba_zhiboba_live_text_event.segmented_text`
9. 观察是否存在需要继续调优的噪声：
   - 无效阶段文本
   - 无意义口语词
   - 中括号比分提示
   - 不应参与分词的整行直播文本
   - 误切分的球员简称或别名
10. 把调优结果写回过滤规则表或别名表。
11. 如规则有变化，重新对该场比赛执行抓取/分词或只重新执行分词。

## 调优依据

### 整行过滤
- 命中后整条记录跳过，不进入分词
- 常见场景：
  - `pid_text='未赛'`
  - `pid_text='中场休息'`
  - 其他确认属于无效阶段的文本

### 文本内容删除
- 只删除噪声片段，保留主体语义
- 常见场景：
  - `[]` 中括号包裹的比分提示
  - 语气助词
  - 无意义标点堆叠

### 球员识别调优
- 如果分词结果把球员名切碎，优先检查：
  - `nba_players_name_data`
  - `player_alias_name_info`
- 需要时补充球员别名，再重新分词

### 规格校验闭环
- 在每一轮抓取和分词后，都要调用 `文本分词规格校验`
- 如果校验结果：
  - `passed = true`
  - 则立即停止后续自动调优
- 如果校验结果：
  - `passed = false`
  - 且本轮确实新增了过滤规则或做了有效调整
  - 则允许继续下一轮自动调优
- 如果校验结果：
  - `passed = false`
  - 但本轮没有新增规则
  - 则必须停止，避免无变化情况下死循环
- 必须设置最大尝试轮数，例如 `max_attempts=3`
- 达到最大尝试次数后即使仍未通过校验，也必须停止

## 数据库对接
- `game_list`
  - 提供待处理比赛 ID
- `nba_zhiboba_live_text_event`
  - 保存抓取后的原始事件和分词展示文本
- `nba_zhiboba_live_text_filter_rule`
  - 保存整行过滤和文本删除规则
- `nba_players_name_data`
  - 提供球员完整名称、主表别名
- `player_alias_name_info`
  - 提供球员中文别名

## 输出要求
- 返回当前处理的比赛信息：
  - `saishi_id`
  - `home_team`
  - `visit_team`
- 返回抓取与分词统计：
  - `pages`
  - `events`
  - `filtered`
  - `finished`
- 返回分词抽样：
  - `live_sid`
  - `live_text`
  - `cleaned_text`
  - `segmented_text`
- 返回本轮新增或调整的过滤规则摘要
- 返回规格校验结果：
  - `passed`
  - `needs_update_fetch_skill`
  - `violation_rule_count`
- 返回自动调优停止原因：
  - `validation_passed`
  - `validation_failed_without_new_rules`
  - `reached_max_attempts`

## 注意事项
- 本 skill 是总调度型 skill，不替代 `比赛文本抓取` 或 `直播文本分词` 的底层职责。
- 默认一次只处理 `game_list` 中的一场比赛。
- 必须防止死循环：
  - 校验通过则停止
  - 没有新增规则则停止
  - 达到最大尝试次数则停止
- 如果用户要求“批量全表跑”，应明确批次大小，避免一次性处理过多比赛。
- 如果只是想抓原始事件，不要调用本 skill，直接调用 `比赛文本抓取`。
- 如果只是想对已有事件重新分词，不要调用本 skill，直接调用 `直播文本分词`。
