# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4900 |
| API | http://localhost:9900 |
| API 文档 | http://localhost:9900/docs |
| Postgres | localhost:5450 |

健康检查：`GET http://localhost:9900/api/health`

## 使用说明

1. 在「考室」「考生」「试卷套」确认基础数据。
2. 打开「排座图」执行间距排座。
3. 在「违规」查看间距或同卷相邻问题。
4. 在「统计」查看占用与违规汇总。

## 封场

在「考室」页对已有排座方案的考室执行封场（空考室从未排过座，不允许封场）。封场时三处在同一事务同时落下：

- **写入口闸**：封场期间 `POST /api/seating/run` 等一切生成新方案入口返回 409，方案条数不变；
- **封场快照仓**：封场当时的排座图、违规、统计整体写入 `seal_snapshots`，之后只读，解封与再排均不改写；
- **待生效配置**：封场期间修改最小间距只进待生效配置（`pending_min_manhattan`），不改快照、不出新方案。

解封（`POST /api/halls/{id}/unseal`）后待生效配置生效，才允许重新排座；新方案按解封当下的约束出图。「封场禁写」与「解封才可写」互斥：重复封场、未封解封均返回 409。

相关接口：`POST /api/halls/{id}/seal`、`POST /api/halls/{id}/unseal`、`PATCH /api/halls/{id}`、`GET /api/halls/{id}/snapshot`。

## 开发与测试

```bash
docker compose exec api pytest -q
```
