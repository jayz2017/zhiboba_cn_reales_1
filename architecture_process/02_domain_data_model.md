# 02 领域与数据建模（门禁：模型评审）

## 输入
- 需求说明与数据字典 V0

## 产物（必须交付）
- 领域实体：Team、Game、ScheduleRaw、LiveTextEvent、SemanticRelation
- 事件流：ScheduleIngested、LiveTextIngested、Tokenized、RelationsExtracted
- 边界上下文：API、Crawler、Parser、NLP、Semantics、Persistence
- 数据一致性策略：幂等键、去重规则、证据链（evidence_live_event_id）

## 检查清单
- 每个实体有唯一标识与幂等规则（例如赛程：season+date+home+away）
- 文本类数据可回放：保留 raw_json / 原始事件文本
- 抽取结果可追溯：必须能定位到原始文本事件
