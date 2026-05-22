---
name: "文本分词规格校验"
description: "校验 nba_zhiboba_live_text_event 的 segmented_text 是否违反 line_skip exact 规则。Invoke when 用户要求检查过滤规则是否真的拦住分词结果时。"
---

# 文本分词规格校验

## 适用场景（何时调用）
- 用户怀疑 `nba_zhiboba_live_text_filter_rule` 中定义的整行过滤规则没有真正生效
- 用户要求检查 `segmented_text` 是否还残留本应整行跳过的文本
- 用户要求判断“比赛文本抓取”与“直播文本分词”之间的规则执行是否一致
- 用户要求定位哪些比赛、哪些事件违反了当前过滤规格

## 校验目标
- 读取 `nba_zhiboba_live_text_event`
- 读取 `nba_zhiboba_live_text_filter_rule`
- 仅针对以下规则做规格校验：
  - `rule_type='line_skip'`
  - `target_field='pid_text'` 或 `target_field='live_text'`
  - `match_mode='exact'`
- 判断这些 `exact` 整行过滤规则对应的 `filter_text`，是否仍出现在事件表的 `segmented_text` 中
- 额外针对以下规则做文本替换规格校验：
  - `rule_type='line_skip'`
  - `target_field='pid_text'` 或 `target_field='live_text'`
  - `match_mode='contains'`
- 判断这些 `contains` 规则对应的 `filter_text`，是否在抓取后的文本中已被替换为空字符串

## 核心判定原则

### 1. `target_field='pid_text' + match_mode='exact'`
- 含义：
  - 如果某条事件的 `pid_text` 精确等于规则中的 `filter_text`
  - 则这条事件本应整行跳过，不应该进入分词结果
- 校验方式：
  - 找出 `pid_text = filter_text` 且 `segmented_text` 非空的事件
- 命中结论：
  - 说明整行过滤未在抓取/分词前生效
  - 应调整 `比赛文本抓取` skill 的规则说明或实现口径

### 2. `target_field='live_text' + match_mode='exact'`
- 含义：
  - 如果某条事件的 `live_text` 精确等于规则中的 `filter_text`
  - 则这条事件本应整行跳过，不应该进入分词结果
- 校验方式：
  - 找出 `live_text = filter_text` 且 `segmented_text` 非空的事件
- 命中结论：
  - 说明整行过滤未在进入分词前生效
  - 应调整 `比赛文本抓取` skill 的规则说明或实现口径

### 3. `segmented_text` 内容校验
- 对于上述两类 `exact` 规则，如果 `segmented_text` 中仍包含对应的 `filter_text`
- 或者该条本应整行跳过的事件仍然存在分词结果
- 都判定为规格不通过

### 4. `match_mode='contains'` 文本替换校验
- 含义：
  - 如果规则为 `line_skip + target_field='pid_text'/'live_text' + match_mode='contains'`
  - 则命中 `filter_text` 的内容，在抓取后的文本中应被替换为空字符串
- 校验方式：
  - 对 `target_field='pid_text'`：
    - 如果 `pid_text` 仍包含 `filter_text`，则规格不通过
  - 对 `target_field='live_text'`：
    - 如果 `live_text` 仍包含 `filter_text`，则规格不通过
  - 如该条事件已进入分词：
    - 如果 `segmented_text` 仍包含 `filter_text`，则规格不通过
- 命中结论：
  - 说明抓取后的文本替换逻辑未按规则执行
  - 应回头调整 `比赛文本抓取` skill 的规则说明或抓取后的文本清洗实现

## 数据库对接

### 规则来源表
- `nba_zhiboba_live_text_filter_rule`

### 被校验表
- `nba_zhiboba_live_text_event`

### 重点字段
- 规则表：
  - `rule_type`
  - `target_field`
  - `match_mode`
  - `filter_text`
  - `is_enabled`
- 事件表：
  - `saishi_id`
  - `live_sid`
  - `pid_text`
  - `live_text`
  - `segmented_text`

## 推荐校验步骤
1. 读取启用中的 `line_skip` 规则。
2. 仅保留 `target_field in ('pid_text', 'live_text')` 的规则。
3. 将规则拆分为：
   - `match_mode='exact'`
   - `match_mode='contains'`
4. 遍历 `nba_zhiboba_live_text_event`。
5. 对 `exact + pid_text` 规则检查：
   - `pid_text = filter_text`
   - 且 `segmented_text` 非空
6. 对 `exact + live_text` 规则检查：
   - `live_text = filter_text`
   - 且 `segmented_text` 非空
7. 对 `contains + pid_text/live_text` 规则检查：
   - 抓取后的对应字段中不应再包含 `filter_text`
8. 补充检查：
   - `segmented_text LIKE %filter_text%`
9. 输出违反规格的事件列表。
10. 如果命中，给出“需要调整比赛文本抓取 skill”的结论。

## 输出要求
- 返回规则命中统计：
  - `rule_id`
  - `target_field`
  - `filter_text`
  - `violation_count`
- 返回违反规格的事件样例：
  - `saishi_id`
  - `live_sid`
  - `pid_text`
  - `live_text`
  - `segmented_text`
- 返回总结结论：
  - `passed=true/false`
  - `needs_update_fetch_skill=true/false`

## 结论规则
- 只要存在任意一条 `exact` 整行过滤规则命中后，事件仍有 `segmented_text`
- 或 `segmented_text` 仍包含该 `filter_text`
- 或存在任意一条 `contains` 替换规则命中后，`pid_text` / `live_text` / `segmented_text` 仍包含该 `filter_text`
- 就应判定：
  - `passed = false`
  - `needs_update_fetch_skill = true`

## 注意事项
- 本 skill 是“规格校验”能力，不直接修改数据库数据。
- 本 skill 主要用于发现规则口径和实际落库行为是否一致。
- 如果发现违反规格，应优先回头检查：
  - `比赛文本抓取`
  - `直播文本分词`
  - `nba_zhiboba_live_text_filter_rule` 中 `exact/contains/prefix` 的配置是否正确
