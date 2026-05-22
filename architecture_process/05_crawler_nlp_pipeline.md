# 05 采集/NLP/语义流水线（门禁：可回放与可追溯）

## 输入
- 数据来源清单与反爬风险

## 产物（必须交付）
- Request 公共封装：统一超时、Header、错误处理（app/utils/http）
- 重试机制封装：指数退避、最大次数、异常白名单（app/utils/crawler）
- 赛程解析：raw → ParsedGame → 入库（app/modules/nba_schedule）
- 直播文本读取：raw → LiveTextEvent → 入库（app/modules/nba_live_text）
- 分词：LiveTextEvent.text → tokens（PaddleNLP `TaskFlow`，按页批量处理，app/modules/nba_live_text/nlp）
- 语义抽取：tokens/text → SemanticRelation（app/modules/semantics）
- 比赛词典：按 `saishi_id` 关联双方球队，再从球员表构建 `user_dict` 注入分词器
- 停用词策略：保留现有语气助词/无意义虚词过滤规则，不因模型替换改变业务口径

## 检查清单
- 任意一批数据都能从 raw 重跑得到同样结果（幂等与去重）
- 出错可定位：源站、批次、原文事件、抽取结果之间可关联
- 重试有上限且可配置，避免雪崩与放大流量
- 分词模型只初始化一次并复用到整页文本，避免逐条推理造成性能回退
