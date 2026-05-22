---
name: "比赛文本抓取"
description: "抓取 dingshi2.qiumibao.com 的比赛直播文本事件并解析落库。Invoke when 用户要求按 saishi_id 抓取直播文本、处理分页/404/终止规则或同步原始事件时。"
---

# 比赛文本抓取（dingshi2 livetext）

## 适用场景（何时调用）
- 用户给出 `saishi_id`，要求抓取整场比赛直播文本
- 用户要求处理分页游标、`404` 自动重试、`pid_text=比赛结束` 自动终止
- 用户要求把原始直播文本事件解析后落入事件表
- 用户要求只做“抓取 + 事件落库”，暂时不做分词

## 数据源

### URL 规则
- 基础 URL：
  - `https://dingshi2.qiumibao.com/livetext/data/cache/livetext/{saishi_id}/0/page_{page_size}/{cursor}.json`
- `saishi_id`：比赛 ID
- `page_size`：每页条数，默认 `10`
- `cursor`：游标，默认从 `1` 开始

### 分页与循环规则
- 初始 `cursor=1`
- 请求成功后：`cursor = cursor + len(返回数组)`
- 若请求返回 `404`：`cursor = cursor + 1`，继续访问下一游标
- 过滤条件：live_pid 为正整数和-1时保留，0时跳过
- 过滤条件：`live_pid` 只保留正整数和 `-1`，其余值直接跳过
- 过滤条件：`live_text` 以 `@` 开头的弹幕评论行直接整行跳过
- 过滤条件：命中 `nba_zhiboba_live_text_filter_rule` 中 `rule_type='line_skip'` 的规则时，整行跳过
- `line_skip` 当前支持：
  - `target_field='pid_text'` 或 `target_field='live_text'`
  - `match_mode='exact'`、`match_mode='contains'`、`match_mode='prefix'`
- 推荐写法：
  - `live_text` 的关键词过滤应使用 `match_mode='contains'`
  - `live_text` 以固定前缀开头的过滤应使用 `match_mode='prefix'`
  - `pid_text` 的阶段值过滤使用 `match_mode='exact'`
- 抓取阶段只使用 `line_skip` 规则，不在此阶段应用 `content_remove`

## 返回字段（原样解析）
- `pid_text`：阶段文本
- `saishi_id`：比赛 ID
- `live_text`：直播内容文本
- `live_text`：直播内容文本
- `live_pid`：比赛节次/阶段
- `visit_score`：客队得分
- `home_score`：主队得分
- `user_chn`：当前直播文本指向的球员名称
- `live_sid`：直播文本行 ID

## 解析增强字段
- 在抓取并落库时，按 `live_sid ASC` 顺序比对同一场比赛上一条事件的比分，自动补充以下字段
- `current_player_name`
  - 当前文本对应的主叙述球员名称
  - 初始取值来自 `user_chn`
- `home_score_change`
  - 相比上一条事件，主队本条文本对应的得分变化值
- `visit_score_change`
  - 相比上一条事件，客队本条文本对应的得分变化值
- `score_team_side`
  - 本条得分发生在哪一侧
  - 可选值：`home` / `visit` / `both`
- `score_points`
  - 本条事件新增得分值
  - 例如主队从 `98 -> 101`，则本字段为 `3`
- `score_diff`
  - 当前时刻分差
  - 计算方式：`home_score - visit_score`

## MySQL 落库

### 表
- `nba_zhiboba_live_text_event`

### 主要字段
- 原始字段：
  - `saishi_id`
  - `live_sid`
  - `live_pid`
  - `pid_text`
  - `live_text`
  - `home_score`
  - `visit_score`
  - `user_chn`
- 解析增强字段：
  - `current_player_name`
  - `home_score_change`
  - `visit_score_change`
  - `score_team_side`
  - `score_points`
  - `score_diff`

### 幂等策略
- 唯一键：`live_sid`
- 写入方式：`INSERT ... ON DUPLICATE KEY UPDATE`

## 规则表说明

### 表
- `nba_zhiboba_live_text_filter_rule`

### 本 skill 实际使用方式
- 只读取 `is_enabled = 1` 的规则
- 只使用 `rule_type='line_skip'`
- 命中后直接整行跳过，不落库、不进入后续增强字段计算

### 示例
- `line_skip + pid_text + exact + 未赛`
  - `pid_text='未赛'` 的整行跳过
- `line_skip + pid_text + exact + 中场休息`
  - `pid_text='中场休息'` 的整行跳过
- `line_skip + live_text + prefix + @`
  - `live_text` 以 `@` 开头的整行弹幕评论直接跳过
- `line_skip + live_text + contains + 裁判`
  - 只要 `live_text` 中包含“裁判”，整行直接跳过
- 兼容迁移说明
  - 旧数据里如果把 `line_skip + live_text + exact` 用成关键词过滤，代码启动时会自动整理：
  - `@` 自动转成 `prefix`
  - 其他 `live_text + exact` 规则自动转成 `contains`

## 执行步骤
1. 按 `saishi_id/page_size/cursor` 组装 URL。
2. 循环抓取 JSON 数组。
3. 解析原始 JSON 为事件对象。
4. 先按 `live_pid` 规则和 `nba_zhiboba_live_text_filter_rule` 的 `line_skip` 规则过滤整行无效数据。
5. 对保留下来的事件按 `live_sid` 顺序计算比分变化、得分值、分差与 `current_player_name`。
6. 将原始字段和增强字段一并写入 `nba_zhiboba_live_text_event`。
7. `404` 则游标 `+1` 后继续。
8. 命中 `pid_text=比赛结束` 后停止。

## 边界说明
- 本 skill 只负责“抓取 + 解析 + 事件落库”。
- 本 skill 不负责分词，不会在抓取阶段执行 `content_remove` 文本删除规则。
- `content_remove` 规则属于 `直播文本分词` 阶段使用的文本清洗能力。
- 如果后续通过 `文本分词规格校验` 发现：
  - `line_skip + target_field='pid_text'/'live_text' + match_mode='exact'`
  - 对应的 `filter_text` 仍然出现在 `segmented_text`
  - 或本应整行跳过的事件仍存在分词结果
  - 则应回头调整本 skill 的规则说明或抓取阶段过滤实现。
- 如果用户还要求分词，请再调用 `直播文本分词`。
