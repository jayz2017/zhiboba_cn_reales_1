---
name: "API总调度"
description: "统筹当前项目全部 FastAPI 接口，按用户自然语言指令分流到健康检查、赛程同步、季后赛同步、球队球员同步或比赛直播文本同步 API。Invoke when 用户明确要调用接口或 Swagger API 时。"
---

# API 总调度（FastAPI 接口总入口）

## 适用场景（何时调用）
- 用户明确说要“调用 API”
- 用户要直接通过 Swagger / FastAPI 接口完成同步任务
- 用户不知道当前已有哪个接口，想根据一句话自动映射 API

## 当前 API 总览

### 1. 健康检查
- 方法：`GET`
- 路径：`/api/v1/health`
- 作用：检查服务是否正常
- 推荐调用指令：
  - `调用健康检查 API`
  - `检查服务状态`
  - `帮我 ping 一下接口`

### 2. 常规赛 / 总赛程同步
- 方法：`POST`
- 路径：`/api/v1/schedule/zhiboba/sync`
- 参数：
  - `year` 可选
- 推荐调用指令：
  - `调用总赛程同步 API`
  - `同步 2025 年赛程接口`
  - `执行直播吧常规赛赛程同步`

### 3. 季后赛对阵同步
- 方法：`POST`
- 路径：`/api/v1/schedule/zhiboba/playoffs/sync`
- 参数：
  - `year` 可选
- 推荐调用指令：
  - `调用季后赛同步 API`
  - `同步 2025 年季后赛对阵`
  - `执行季后赛赛程接口`

### 4. 球队球员同步
- 方法：`POST`
- 路径：`/api/v1/team/zhiboba/players/sync`
- 参数：
  - `team_id` 必填
- 推荐调用指令：
  - `调用球队球员同步 API，team_id=6916`
  - `执行球队球员接口`
  - `同步指定球队的球员列表`

### 5. 全量同步全部 NBA 球队球员
- 方法：`POST`
- 路径：`/api/v1/team/zhiboba/players/sync/all`
- 作用：
  - 自动从 `nba_teams_name_data` 读取 `team_type='NBA'` 的球队
  - 逐条使用 `zhiboba_team_id` 循环抓取球队球员
  - 自动补齐球员详情中的 `playerCode`
- 推荐调用指令：
  - `调用全部NBA球队球员同步 API`
  - `自动从球队表读取 NBA 球队并同步球员`
  - `执行全量球队球员同步`

### 6. 按球队主表 team_id 同步球员
- 方法：`POST`
- 路径：`/api/v1/team/players/sync/by-team-id`
- 参数：
  - `team_id` 必填
- 推荐调用指令：
  - `调用按球队ID同步球员 API，team_id=1610612747`
  - `根据球队主表 team_id 同步球员`
  - `执行球队主表映射球员接口`

### 7. 按 zhiboba_team_id 绑定球员表 team_id
- 方法：`POST`
- 路径：`/api/v1/team/players/bind/team-id/by-zhiboba-team-id`
- 参数：
  - `zhiboba_team_id` 必填
- 推荐调用指令：
  - `调用按直播吧球队ID绑定球员 team_id API，zhiboba_team_id=6916`
  - `按 zhiboba_team_id 修正球员表 team_id`
  - `根据 zhiboba_team_id 匹配球队名称并更新球员 team_id`

### 8. 比赛直播文本同步
- 方法：`POST`
- 路径：`/api/v1/live-text/zhiboba/sync`
- 参数：
  - `saishi_id` 必填
  - `start_cursor` 可选，默认 `1650`
  - `page_size` 可选，默认 `10`
- 推荐调用指令：
  - `调用比赛直播文本同步 API，saishi_id=1976690`
  - `执行直播文本抓取接口`
  - `按 1650 起点同步比赛文本 API`

### 9. 球员别名同步
- 方法：`POST`
- 路径：`/api/v1/player-alias/sync`
- 参数：
  - `saishi_id` 可选，不传则自动从 `nba_zhiboba_yj_gamelist` 全量读取
- 作用：
  - 根据 `game_date + saishi_id` 抓取球员中文别名
  - 写入 `player_alias_name_info`
  - 按 `player_id + alias_name` 去重
- 推荐调用指令：
  - `调用球员别名同步 API`
  - `同步比赛球员中文别名`
  - `按 saishi_id 同步球员别名`

## Swagger 入口
- Swagger 地址：
  - `http://localhost:8000/docs`
- 推荐调用指令：
  - `打开 Swagger`
  - `显示 API 文档`
  - `我要看所有接口`

## 指令到 API 的映射规则
- 如果用户提到：
  - `健康 / 状态 / ping`
  - 调用 `GET /api/v1/health`
- 如果用户提到：
  - `总赛程 / 常规赛 / 赛程同步`
  - 调用 `POST /api/v1/schedule/zhiboba/sync`
- 如果用户提到：
  - `季后赛 / playoffs / 对阵`
  - 调用 `POST /api/v1/schedule/zhiboba/playoffs/sync`
- 如果用户提到：
  - `球队球员 / team_id / 球员同步`
  - 调用 `POST /api/v1/team/zhiboba/players/sync`
- 如果用户提到：
  - `全部NBA球队球员 / 全量球队球员同步 / 从球队表读取 NBA 球队`
  - 调用 `POST /api/v1/team/zhiboba/players/sync/all`
- 如果用户提到：
  - `主表 team_id / 根据球队ID同步球员 / 球队表映射球员`
  - 调用 `POST /api/v1/team/players/sync/by-team-id`
- 如果用户提到：
  - `zhiboba_team_id / 绑定球员 team_id / 修正球员 team_id / 匹配球队名称更新`
  - 调用 `POST /api/v1/team/players/bind/team-id/by-zhiboba-team-id`
- 如果用户提到：
  - `比赛文本 / 直播文本 / saishi_id / 比赛直播文本同步`
  - 调用 `POST /api/v1/live-text/zhiboba/sync`
- 如果用户提到：
  - `球员别名 / 中文别名 / alias_name / player_alias_name_info`
  - 调用 `POST /api/v1/player-alias/sync`

## 直接可用的自然语言指令模板
- `调用健康检查 API`
- `调用总赛程同步 API，year=2025`
- `调用季后赛同步 API，year=2025`
- `调用球队球员同步 API，team_id=6916`
- `调用全部NBA球队球员同步 API`
- `调用按球队ID同步球员 API，team_id=1610612747`
- `调用按直播吧球队ID绑定球员 team_id API，zhiboba_team_id=6916`
- `调用比赛直播文本同步 API，saishi_id=1976690，start_cursor=1650，page_size=10`
- `调用球员别名同步 API，saishi_id=1977335`
- `打开 Swagger 文档`

## 调用优先级
- 用户如果明确要“接口执行”，优先走本 skill。
- 用户如果明确要“业务能力”而不是“接口”，优先走 `全局总管理` 再分流到具体 skill。

## 注意事项
- 本 skill 只负责 API 级别总调度与映射，不替代具体业务 skill 的实现说明。
- 调用 API 前应确认服务已启动，Swagger 默认入口为 `http://localhost:8000/docs`。
