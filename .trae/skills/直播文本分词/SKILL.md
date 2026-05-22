---
name: "直播文本分词"
description: "使用 PaddleNLP TaskFlow 对比赛直播文本做分词并回写 segmented_text。Invoke when 用户要求对 live_text 分词、按球员词典优先切分或对分词结果做分析时。"
---

# 直播文本分词（PaddleNLP TaskFlow）

## 适用场景（何时调用）
- 用户要求对 `live_text` 做中文分词
- 用户要求优先识别本场比赛双方球员名称，不要把球员名拆碎
- 用户要求分词结果落库，或基于分词结果做后续分析

## 分词实现

### 模型
- 使用 PaddleNLP 2.7+：
  - `Taskflow("word_segmentation", mode="accurate", user_dict=...)`
- 默认采用 `accurate` 智能分词模式：
  - 提升中文切分精度
  - 继续支持通过 `user_dict` 注入比赛级词典
  - 适合直播文本里的球员名、简称、别名优先整体识别

### 输出要求
- 只输出词语数组：
  - `["词1", "词2", ...]`
- 不追加解释性文本
- 如需展示分词效果，应额外输出一份分词展示文本：
  - 使用 `\` 连接切分后的 token
  - 示例：
    - 原文：`詹姆斯突破上篮打进`
    - 展示：`詹姆斯\突破\上篮\打进`

## 直播文本过滤
- 在处理直播文本事件前，先过滤无效或未开赛事件
- 过滤规则：
  - `pid_text = '未赛'` 的数据直接跳过，不参与分词
  - `pid_text = '中场休息'` 的数据直接跳过，不参与分词
  - `live_pid` 只保留正整数和 `-1`；其余值直接跳过，不参与分词
  - `live_text` 以 `@` 开头的弹幕评论行直接跳过，不参与分词
  - `live_text` 的关键词整行过滤建议在规则表中使用 `line_skip + live_text + contains`
- 文本清洗规则：
  - 类似 `[火箭0-2雷霆]` 这样的中括号片段会连同 `[]` 一起删除
  - 类似 `@玉鼎山人里斯夫：` 这样的弹幕用户名引用前缀会在分词前整段删除
  - 删除后不在 `cleaned_text`、`segmented_text` 和 token 落库结果中体现
- 只对有效的 `live_text` 文本执行分词
- 如果过滤后文本为空，则该条记录跳过

## 球员词典优先级

### 查询逻辑
1. 通过 `saishi_id` 查询比赛双方信息。
2. 根据双方球队批量查询本场参赛球员名单。
3. 从 `nba_players_name_data` 读取球员完整名、直播吧名、主表别名。
4. 从 `player_alias_name_info` 读取已同步的球员中文别名。
5. 将球员完整名 + 球员别名共同写入 `user_dict`。
6. 交给 PaddleNLP `TaskFlow` 分词，保证球员姓名和别名优先整体切分。

### 数据库对接
- `nba_zhiboba_yj_gamelist`
  - 根据赛事 ID 查询主队、客队
- `nba_players_name_data`
  - 根据球队 ID 查询本场球员完整名、标准名、别名
- `player_alias_name_info`
  - 读取球员中文别名并与主表球员做归一化映射

### 展示归一化
- 分词后的展示文本 `segmented_text` 仍使用 `\` 连接 token。
- 如果 token 命中球员别名、简称或主表中的其他别名：
  - 展示时替换为球员信息表中的完整球员名称
- `current_player_name` 同样会基于球员别名映射归一化：
  - 如果 `user_chn` 命中别名，则回写为球员完整名称
- 完整球员名称优先级：
  - `nba_players_name_data.nba_player_name`
  - `nba_players_name_data.zhiboba_player_name`

## 停用词过滤
- 保持原业务逻辑不变
- 自动剔除语气助词、无意义虚词，例如：
  - `啊/呀/吧/呢/吗/啦/哦/诶/哎/哈`

## MySQL 回写

### 表
- `nba_zhiboba_live_text_event`

### 回写字段
- `segmented_text`
  - 保存直播文本分词后的展示结果
  - 使用 `\` 连接最终 token
  - 示例：`詹姆斯\突破\上篮\打进`
- `current_player_name`
  - 保存当前文本对应的持球人/主叙述球员名称
  - 来源于 `user_chn`，并参与别名归一化
- `home_score_change`
  - 主队相对上一条 `live_sid` 事件的得分变化
- `visit_score_change`
  - 客队相对上一条 `live_sid` 事件的得分变化
- `score_team_side`
  - 本条得分发生在主队、客队还是双方
  - 可选值：`home` / `visit` / `both`
- `score_points`
  - 本条事件新增得分值
- `score_diff`
  - 当前时刻分差，计算方式：`home_score - visit_score`

## 执行步骤
1. 读取待处理的 `live_text` 事件。
2. 先过滤 `pid_text='未赛'`、`pid_text='中场休息'` 以及无效 `live_pid` 的记录。
3. 查询本场比赛双方球员完整名与别名并生成 `user_dict`。
4. 使用 `Taskflow("word_segmentation", mode="accurate", user_dict=...)` 对当前页或当前批次文本做批量分词。
5. 过滤停用词。
6. 额外清理 `@用户名：` 这类弹幕引用前缀，避免用户名进入分词结果。
7. 对命中的球员别名做标准名归一化替换。
8. 按 `live_sid` 顺序比对上一条事件比分，计算得分变化、得分方、得分值与当前分差。
9. 将归一化后的 token 用 `\` 拼接输出分词结果。
10. 将 `segmented_text`、`current_player_name`、`home_score_change`、`visit_score_change`、`score_team_side`、`score_points`、`score_diff` 一并回写到 `nba_zhiboba_live_text_event`。

## 边界说明
- 本 skill 只负责“分词 + 词典 + segmented_text 回写”。
- 如果用户要求从源站抓取原始直播文本，请先调用 `比赛文本抓取`。
- `pid_text='未赛'`、`pid_text='中场休息'` 属于无效分词输入，应在进入分词流程前剔除。
- `live_pid` 只有正整数和 `-1` 允许进入分词环节。
- 中括号包裹的比分提示、备注提示等内容属于展示噪声，应在分词前整体移除。

## 扩展建议
- 如后续继续补充更多球员简称或解说口语别名，只需要先同步到 `player_alias_name_info` 或主表别名字段即可自动参与识别。
- 批量赛事处理时，可在外层循环多个 `saishi_id`，本 skill 仍只关注单场或单批次分词。
