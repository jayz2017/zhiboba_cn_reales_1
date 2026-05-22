# 08 PaddleNLP TaskFlow 替换说明

## 目标
- 将项目内直播文本分词能力从显式 `jieba` 调用替换为 PaddleNLP `TaskFlow`
- 保持原有业务口径不变：球员词典优先级、停用词过滤、分页/404/终止逻辑、分词结果落库

## 替换范围
- 依赖：移除项目显式 `jieba` 依赖，新增 `paddlepaddle` 与 `paddlenlp`
- 代码：
  - `app/modules/nba_live_text/nlp/tokenizer.py`
  - `app/modules/nba_live_text/zhiboba_livetext.py`
- 测试：
  - `tests/test_tokenizer.py`
  - `tests/test_zhiboba_livetext.py`

## 新调用方式
- 分词入口统一走 `Tokenizer`
- `Tokenizer` 内部使用：
  - `Taskflow("word_segmentation", mode="accurate", user_dict=...)`
- 自定义球员词典：
  - 先按 `saishi_id` 查询比赛双方
  - 再按双方球队查询本场球员完整名、直播吧名、主表别名
  - 再读取 `player_alias_name_info` 中已同步的中文别名
  - 动态写入 `user_dict.txt` 后交给 TaskFlow
  - 分词后将球员别名统一替换为球员信息表中的完整名称

## 行为保持
- 直播文本抓取仍保留：
  - `start_cursor=1650` 默认起点
  - 404 自动 `+1` 重试
  - 成功后按返回条数累加游标
  - 遇到 `pid_text=比赛结束` 自动终止
- 停用词过滤规则不变
- 事件表与 token 表落库策略不变

## 性能优化
- 原实现逐条分词
- 新实现改为“按页批量分词”，一次将当前页 `live_text` 列表传入 TaskFlow
- 收益：
  - 降低 Python 层循环开销
  - 避免每条文本单独推理导致的吞吐波动
  - 更适合直播文本分页抓取场景

## 兼容性说明
- 当前目标环境升级到 PaddleNLP 2.7+ 后，直播文本分词统一切换到 `mode="accurate"`
- 保留 `user_dict` 动态词典机制，保证球员全名、简称、别名优先整体切分
- 如果未来再升级 Paddle/PaddleNLP 版本，优先通过 `Tokenizer` 内部适配，不改业务入口

## 维护建议
- 抓取与分词建议拆成两个独立 skill：
  - `比赛文本抓取`：负责分页抓取、字段解析、事件落库
  - `直播文本分词`：负责 TaskFlow 分词、球员词典注入、停用词过滤、token 落库
- 如果后续需要更高精度模型，优先在 `Tokenizer` 内部扩展，不直接改业务流程代码
