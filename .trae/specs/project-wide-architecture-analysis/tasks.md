# 项目全局架构分析与优化 - 任务清单

## 第一阶段：修复严重问题（P0）

- [x] **T0-1**: 引入 Alembic 迁移管理
  - [x] T0-1.1: 安装 alembic 依赖 `pip install alembic`
  - [x] T0-1.2: 初始化 alembic `alembic init migrations`
  - [x] T0-1.3: 配置 alembic.ini 指向当前数据库
  - [x] T0-1.4: 将现有 DDL 转换为初始迁移脚本 (556ad3133c78)
  - [x] T0-1.5: 保持运行时 DDL 检查逻辑（向后兼容）
  - [x] T0-1.6: 验证迁移脚本可正确执行

- [x] **T0-2**: 批量INSERT优化（5个模块）
  - [x] T0-2.1: `zhiboba_livetext.py` 已使用 executemany
  - [x] T0-2.2: `zhiboba_schedule.py` 已使用 executemany
  - [x] T0-2.3: `zhiboba_team_players.py` 已使用 executemany
  - [x] T0-2.4: `player_alias.py` 已使用 executemany
  - [x] T0-2.5: `game_list_by_date.py` 已使用 executemany

- [x] **T0-3**: f-string SQL参数化
  - [x] T0-3.1: 修复 `zhiboba_team_players.py` 中 `build_nba_team_filter_sql` 的SQL拼接（白名单验证）
  - [x] T0-3.2: 修复 `zhiboba_livetext.py` 中 `load_player_segmentation_config` 的SQL拼接（白名单验证）
  - [x] T0-3.3: 添加白名单验证动态列名（3处）

- [x] **T0-4**: 异常日志补充
  - [x] T0-4.1: 修复 `zhiboba_livetext.py` 吞掉的异常（3处）
  - [x] T0-4.2: 修复 `zhiboba_team_players.py` 吞掉的异常
  - [x] T0-4.3: 修复 `player_alias.py` 异常日志增强

- [x] **T0-5**: 递归深度限制
  - [x] T0-5.1: `zhiboba_team_players.py` 的 `_find_first_str_value` 添加 max_depth
  - [x] T0-5.2: `player_alias.py` 的 `_collect_alias_records` 添加 max_depth

## 第二阶段：架构优化（P1）

- [x] **T1-1**: 拆分 siamese_uie.py (1473行 → 829行)
  - [x] T1-1.1: 创建 `orchestrator.py` 提取 `extract_postgame_player_relations` 编排逻辑
  - [x] T1-1.2: 创建 `uie_result_parser.py` 提取 UIE 结果解析
  - [x] T1-1.3: 删除 siamese_uie.py 中的重复代码
  - [x] T1-1.4: 更新所有导入引用

- [x] **T1-2**: 拆分 zhiboba_livetext.py (1297行 → 835行)
  - [x] T1-2.1: 创建 `livetext_schema.py` 提取数据模型和DDL
  - [x] T1-2.2: 创建 `livetext_filter.py` 提取过滤规则
  - [x] T1-2.3: 更新所有导入引用

- [x] **T1-3**: 统一辅助函数
  - [x] T1-3.1: `_canonical_text` 统一到 `context_builder.py`
  - [x] T1-3.2: `_get_player_team_info` 统一到 `context_builder.py`
  - [x] T1-3.3: `_row_score_points` 统一到 `context_builder.py`
  - [x] T1-3.4: 删除其他位置的重复实现（siamese_uie.py + rule_extractor.py）

- [x] **T1-4**: 明确模块职责边界
  - [x] T1-4.1: 创建 `__all__` 明确公开接口（6个模块）
  - [x] T1-4.2: 添加 docstring 说明模块职责

## 第三阶段：代码质量（P2）

- [x] **T2-1**: 配置值参数化
  - [x] T2-1.1: 数据库连接池配置参数化
  - [x] T2-1.2: HTTP超时配置参数化
  - [x] T2-1.3: UIE批次大小参数化
  - [x] T2-1.4: 子进程超时参数化
  - [x] T2-1.5: 最大重试次数参数化

- [x] **T2-2**: datetime.utcnow()替换
  - [x] T2-2.1: `service.py` 替换为 `datetime.now(timezone.utc)`

- [x] **T2-3**: retry策略优化
  - [x] T2-3.1: 默认重试异常类型已修正
  - [x] T2-3.2: 重试日志回调已添加

- [x] **T2-4**: 健康检查增强
  - [x] T2-4.1: 数据库连接检查已添加
  - [x] T2-4.2: 503状态码已实现

- [x] **T2-5**: 全局异常处理
  - [x] T2-5.1: 在 `main.py` 添加 `@app.exception_handler`（Exception + ValueError）
  - [x] T2-5.2: 统一错误响应格式

## 第四阶段：可选优化（P3）

- [x] **T3-1**: 关键词精度优化
  - [x] T3-1.1: 评估当前关键词匹配效果
  - [x] T3-1.2: 优化过于宽泛的关键词（添加注释）
  - [x] T3-1.3: 修复 `_CONTEST_KEYWORDS` 拼写 bug

- [x] **T3-2**: 置信度配置化
  - [x] T3-2.1: 从 `constants.py` 加载置信度配置
  - [x] T3-2.2: 支持运行时调整（rule_config.py + 数据库表）

- [x] **T3-3**: 废弃代码清理
  - [x] T3-3.1: 确认 `reader.py` 无引用后删除
  - [x] T3-3.2: `_ALTER_PLAYER_RELATION_COLUMNS` 不存在（无需清理）