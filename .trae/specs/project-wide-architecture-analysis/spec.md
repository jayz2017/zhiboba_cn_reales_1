# 项目全局架构分析与优化方案

## Why

当前项目存在以下系统性架构和质量问题，需要系统性优化：

1. **架构层面**：模块职责划分不清晰，部分模块文件过大（1400+行），数据流不明确
2. **代码质量**：存在大量重复代码、安全隐患、异常处理不当、资源泄漏等问题
3. **可维护性**：硬编码值多、配置分散、测试覆盖率低
4. **可扩展性**：紧耦合导致难以扩展新功能或替换底层实现

## What Changes

### 一、项目架构分析

#### 1.1 当前模块结构

```
app/
├── core/                      # 基础设施层
│   ├── config.py              # 配置管理（36行）
│   ├── database.py            # 数据库连接（25行）
│   ├── http_resources.py      # HTTP资源管理（104行）
│   └── main.py               # FastAPI应用入口（18行）
│
├── modules/                   # 业务逻辑层
│   ├── nba_live_text/        # 直播文本处理
│   │   ├── zhiboba_livetext.py  # 直播吧文本（1165行 ⚠️）
│   │   ├── nba_china_livetext.py # NBA中国文本（820行）
│   │   ├── auto_tune.py          # 自动调优（434行）
│   │   ├── reader.py             # 文本读取器（47行）
│   │   └── nlp/tokenizer.py      # 分词器（264行）
│   │
│   ├── nba_schedule/         # 赛程与球员
│   │   ├── zhiboba_schedule.py    # 直播吧赛程（209行）
│   │   ├── zhiboba_team_players.py # 球队球员（436行）
│   │   ├── player_alias.py       # 球员别名（312行）
│   │   ├── game_list_by_date.py  # 赛程明细（452行）
│   │   ├── nba_china_players.py  # NBA中国球员（760行）
│   │   └── service.py            # 赛程服务（72行）
│   │
│   └── semantics/            # 语义关系抽取 ⚠️ 架构最复杂
│       ├── siamese_uie.py       # 主入口（1473行 ⚠️）
│       ├── incremental_service.py # 增量抽取（869行）
│       ├── context_builder.py     # 上下文构建（462行）
│       ├── models.py             # 数据模型（212行）
│       ├── schema.py             # 数据库DDL（174行）
│       ├── quality_filters.py     # 质量过滤（355行）
│       ├── validators.py          # 数据验证（414行）
│       ├── repository.py          # 数据访问（426行）
│       ├── extractor.py           # 简单抽取器（92行 ⚠️）
│       └── extractors/           # 抽取器策略
│           ├── base.py            # 抽象基类（71行）
│           ├── uie_extractor.py   # UIE抽取（208行）
│           └── rule_extractor.py  # 规则抽取（882行 ⚠️）
│
├── api/v1/endpoints/        # API层
│   ├── live_text.py          # 直播文本API（303行）
│   ├── schedule.py            # 赛程API（134行）
│   └── health.py             # 健康检查（9行）
│
└── utils/                    # 工具层
    ├── http/client.py         # HTTP客户端（118行）
    ├── crawler/retry.py       # 重试机制（24行）
    └── db_helpers.py         # 数据库辅助（新建）
```

#### 1.2 数据流架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据采集层                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐│
│  │直播吧赛程   │  │直播吧球员   │  │直播吧文本   │  │NBA中国球员  ││
│  │同步        │  │同步        │  │抓取+分词   │  │同步        ││
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘│
└─────────┼────────────────┼────────────────┼────────────────┼───────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         数据存储层                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐│
│  │game_list   │  │nba_players │  │nba_zhiboba │  │nba_players ││
│  │            │  │_name_data  │  │_live_text  │  │_china_    ││
│  │            │  │            │  │_event      │  │players    ││
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘│
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         语义抽取层                                     │
│  ┌───────────────────────────────────────────────────────────────┐    │
│  │  关系抽取引擎 (siamese_uie.py + rule_extractor.py)         │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │    │
│  │  │ 上下文构建  │→│  关系抽取   │→│  质量过滤   │         │    │
│  │  │             │  │ (UIE/规则) │  │             │         │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘         │    │
│  └───────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         数据输出层                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  nba_zhiboba_player_relation (球员关系表)                    │  │
│  │  nba_zhiboba_extraction_progress (抽取进度表)                │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 二、已识别的问题清单

#### 2.1 P0 严重问题（必须修复）

| ID | 问题 | 严重程度 | 影响范围 |
|----|------|---------|---------|
| P0-01 | **DDL硬编码在Python代码中** | 严重 | 10+个模块 |
| P0-02 | **逐条INSERT性能差** | 严重 | 5个upsert函数 |
| P0-03 | **f-string SQL拼接** | 严重安全 | 3个模块 |
| P0-04 | **异常被吞掉无日志** | 严重 | 5个模块 |
| P0-05 | **递归无深度限制** | 严重 | 2个递归函数 |

#### 2.2 P1 架构问题（强烈建议）

| ID | 问题 | 严重程度 | 影响范围 |
|----|------|---------|---------|
| P1-01 | **siamese_uie.py 1473行** | 高 | semantics模块 |
| P1-02 | **zhiboba_livetext.py 1165行** | 高 | live_text模块 |
| P1-03 | **rule_extractor.py 882行** | 高 | extractors模块 |
| P1-04 | **代码重复严重** | 高 | 6个模块 |
| P1-05 | **模块职责边界模糊** | 中 | 多个模块 |
| P1-06 | **数据流不清晰** | 中 | 整体架构 |

#### 2.3 P2 代码质量问题（建议修复）

| ID | 问题 | 严重程度 | 影响范围 |
|----|------|---------|---------|
| P2-01 | **硬编码配置值** | 中 | 多个模块 |
| P2-02 | **datetime.utcnow()弃用** | 低 | service.py |
| P2-03 | **retry默认重试所有异常** | 中 | retry.py |
| P2-04 | **健康检查过于简单** | 低 | health.py |
| P2-05 | **缺少全局异常处理** | 中 | main.py |

#### 2.4 P3 轻微问题（可选优化）

| ID | 问题 | 严重程度 | 影响范围 |
|----|------|---------|---------|
| P3-01 | **关键词过于宽泛** | 低 | semantics模块 |
| P3-02 | **置信度硬编码** | 低 | siamese_uie.py |
| P3-03 | **超时硬编码** | 低 | uie_extractor.py |
| P3-04 | **reader.py疑似废弃** | 低 | nba_live_text模块 |
| P3-05 | **随机数做缓存破坏** | 低 | 2个模块 |

### 三、详细问题分析

#### 3.1 P0-01: DDL硬编码

**问题描述**：10+个模块在Python代码中直接写DDL语句

**影响文件**：
- `zhiboba_livetext.py` (198-239行)
- `zhiboba_schedule.py` (131-154行)
- `zhiboba_team_players.py` (169-193行)
- `player_alias.py` (123-161行)
- `game_list_by_date.py` (63-121行)
- `siamese_uie.py` (38-55行) - 已修复为死代码

**优化方案**：
1. 引入 Alembic 进行数据库迁移管理
2. 将所有DDL迁移到 `migrations/` 目录
3. 运行时不再执行DDL检查，依赖迁移版本

#### 3.2 P0-02: 逐条INSERT性能差

**问题描述**：5个upsert函数逐条执行INSERT，性能极差

**影响文件**：
- `upsert_live_text_events` - zhiboba_livetext.py
- `upsert_zhiboba_schedule_records` - zhiboba_schedule.py
- `upsert_zhiboba_team_player_records` - zhiboba_team_players.py
- `upsert_player_alias_records` - player_alias.py
- `upsert_game_list_records` - game_list_by_date.py

**优化方案**：
```python
# 原来: for record in records: db.execute(sql, params)
# 现在: db.execute(sql, [params for params in records])  # executemany
```

#### 3.3 P0-03: f-string SQL拼接

**问题描述**：使用f-string拼接SQL，存在注入风险

**问题代码示例**：
```python
# zhiboba_team_players.py L55
sql = f"SELECT id FROM nba_players_name_data WHERE {column_name} = '{value}'"
```

**优化方案**：
1. 使用参数化查询
2. 白名单验证列名
3. 避免动态列名

#### 3.4 P1-01: siamese_uie.py 1473行

**问题描述**：单个文件超过1400行，违反单一职责原则

**拆分建议**：
```
siamese_uie.py (1473行)
    ├── orchestrator.py (编排层，200行)      # extract_postgame_player_relations
    ├── uie_result_parser.py (300行)          # build_relation_records_from_uie_result
    ├── rule_fallback.py (400行)              # build_relation_records_with_rule_fallback
    ├── data_access.py (200行)                 # upsert_player_relations (已有repository.py)
    └── constants.py (已拆分)                 # 关键词和置信度常量
```

#### 3.5 P1-04: 代码重复严重

**重复清单**：

| 重复内容 | 位置 | 重复次数 |
|---------|------|---------|
| 关键词常量 | siamese_uie.py ↔ rule_extractor.py ↔ constants.py | 3处 |
| 辅助函数 | _canonical_text, _get_player_team_info 等 | 5+处 |
| 置信度值 | 多处硬编码 | 10+处 |
| _to_int/_to_decimal | game_list_by_date.py ↔ zhiboba_livetext.py | 2处 |

**优化方案**：
- 已完成：关键词和置信度提取到 `constants.py`
- 待完成：辅助函数统一到 `context_builder.py` 或 `utils/`
- 待完成：数据库辅助函数统一到 `db_helpers.py`

#### 3.6 P2-01: 硬编码配置值

| 配置项 | 当前值 | 建议 |
|--------|--------|------|
| 数据库连接池大小 | 10 | 可配置 |
| HTTP请求超时 | 15秒 | 可配置 |
| UIE模型批次大小 | 8 | 可配置 |
| 子进程超时 | 240秒 | 可配置 |
| 最大重试次数 | 5 | 可配置 |

### 四、优化方案汇总

#### 4.1 第一阶段：修复严重问题（P0）

| 任务 | 修复内容 | 工作量 |
|------|---------|--------|
| T0-1 | 引入 Alembic 迁移管理 | 中 |
| T0-2 | 批量INSERT优化（5个模块） | 小 |
| T0-3 | f-string SQL参数化 | 中 |
| T0-4 | 异常日志补充 | 小 |
| T0-5 | 递归深度限制 | 小 |

#### 4.2 第二阶段：架构优化（P1）

| 任务 | 修复内容 | 工作量 |
|------|---------|--------|
| T1-1 | 拆分 siamese_uie.py | 大 |
| T1-2 | 拆分 zhiboba_livetext.py | 大 |
| T1-3 | 统一辅助函数 | 中 |
| T1-4 | 明确模块职责边界 | 中 |

#### 4.3 第三阶段：代码质量（P2）

| 任务 | 修复内容 | 工作量 |
|------|---------|--------|
| T2-1 | 配置值参数化 | 小 |
| T2-2 | datetime.utcnow()替换 | 小 |
| T2-3 | retry策略优化 | 小 |
| T2-4 | 健康检查增强 | 小 |
| T2-5 | 全局异常处理 | 中 |

#### 4.4 第四阶段：可选优化（P3）

| 任务 | 修复内容 | 工作量 |
|------|---------|--------|
| T3-1 | 关键词精度优化 | 小 |
| T3-2 | 置信度配置化 | 小 |
| T3-3 | 废弃代码清理 | 小 |

### 五、预期收益

| 维度 | 当前状态 | 优化后 |
|------|---------|--------|
| 代码行数（最大文件） | 1473行 | <500行 |
| 代码重复率 | >20% | <5% |
| SQL注入风险点 | 5+ | 0 |
| 可测试性 | 低 | 高 |
| 可扩展性 | 低 | 高 |

## Impact

### 影响的规格

- 数据采集规格
- 球员关系抽取规格
- 数据质量规格

### 影响的代码

- `app/modules/semantics/` - 需要大规模重构
- `app/modules/nba_live_text/` - 需要拆分
- `app/modules/nba_schedule/` - 优化
- `app/core/` - 配置增强

## ADDED Requirements

### Requirement: 数据库迁移管理
系统 SHALL 使用 Alembic 进行数据库迁移管理，所有DDL通过迁移脚本管理。

#### Scenario: 新增表字段
- WHEN 开发者需要新增表字段
- THEN 在 `migrations/versions/` 目录创建迁移脚本
- AND 运行 `alembic upgrade head` 执行迁移

### Requirement: 配置中心化
系统 SHALL 将所有硬编码配置值提取到配置文件中。

#### Scenario: 修改超时配置
- WHEN 运维需要修改HTTP超时
- THEN 在 `.env` 或 `config.py` 中修改 `REQUEST_TIMEOUT_SECONDS`
- AND 不需要修改代码

### Requirement: 代码复用
系统 SHALL 通过公共模块实现代码复用，减少重复代码。

#### Scenario: 使用数据库辅助函数
- WHEN 开发者需要转换数据类型
- THEN 从 `app.utils.db_helpers` 导入 `to_int`, `to_decimal`
- AND 不需要重复实现

## MODIFIED Requirements

### Requirement: 关系抽取质量过滤
**MODIFIED**: 攻防关系类型集合需与实际使用保持同步。

**原要求**: 硬编码关系类型列表
**新要求**: 从 `constants.py` 导入关系类型常量，确保与抽取器一致

### Requirement: 增量抽取服务
**MODIFIED**: 调用完整的 `RuleBasedExtractor` 而非简陋正则。

**原要求**: 调用 `extractor.py` 的简单正则
**新要求**: 调用 `RuleBasedExtractor.extract_from_rows` 获取完整关系

## REMOVED Requirements

### Requirement: 废弃代码清理
**待移除**: `reader.py` 旧版实现
**Reason**: 与主模块数据格式不一致且未被使用
**Migration**: 确认无引用后删除文件

**待移除**: `_ALTER_PLAYER_RELATION_COLUMNS` 死代码
**Reason**: 已废弃的迁移代码
**Migration**: 直接删除常量定义

## Implementation Notes

### 迁移策略

1. **不影响现有功能**：所有修改必须保证向后兼容
2. **渐进式重构**：大文件拆分分步进行
3. **测试驱动**：先写测试再重构
4. **Git管理**：每次重构提交，记录迁移步骤

### 风险评估

| 重构项 | 风险等级 | 缓解措施 |
|--------|---------|---------|
| siamese_uie.py拆分 | 高 | 保留原接口，内部委托 |
| DDL迁移 | 高 | 备份数据，测试环境先行 |
| SQL参数化 | 中 | 白名单验证 |
| 批量INSERT | 低 | 保持原有语义 |

### 建议的目录重组

```
app/
├── core/                      # 基础设施层（不变）
├── modules/                   # 业务逻辑层（重构）
│   ├── live_text/             # 合并 nba_live_text + nba_china_livetext
│   ├── schedule/               # 合并 nba_schedule 下所有模块
│   └── semantics/              # 拆分优化
│       ├── orchestrator/       # 编排层
│       ├── extractors/          # 抽取器策略
│       ├── models/             # 数据模型
│       ├── services/            # 业务服务
│       └── infrastructure/      # 数据库访问
├── api/v1/endpoints/          # API层（优化）
└── utils/                      # 工具层（统一）
```
