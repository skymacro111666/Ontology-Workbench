# 日志规范（schema_version 1）

服务输出结构化 JSON 日志：每行一个合法 JSON 对象,stdout + 按日轮转文件(`{data_dir}/logs/ow-server.log`,保留 15 天)。UTC、ISO 8601、毫秒耗时。

## 公共字段(所有事件)

| 字段 | 说明 |
|---|---|
| `event` | 事件名,见下表 |
| `service` | 恒为 `ontology-workbench` |
| `service_version` | 包版本(源码树运行落 `dev`) |
| `schema_version` | 字段集版本,当前 `1`;字段不兼容变更时递增 |
| `level` | `info` / `warning` / `error` |
| `timestamp` | **事件发生时刻**。对 `http.request` 即响应完成时刻(不是请求开始) |

字段缺省语义:**不适用的字段整体缺席,不落 `null` 占位**——缺键读作「不适用」,`null` 读作「未知」。

## level 规则

- `info`:成功的业务事件、正常访问日志
- `warning`:慢请求(access log > 5s 升级)、`http.error` 中的 4xx/业务错误
- `error`:**failed 类业务事件**(`*.import_failed`、`*.delete_failed`)与 5xx

## 事件清单

### `http.request`(访问日志,每请求一行)

| 字段 | 说明 |
|---|---|
| `method` / `path` | 原始方法与路径 |
| `route` | 参数化路由模板(如 `/api/ontologies/{ontology_id}/meta`);未匹配(404)回落原始 path。**指标聚合用此字段**,避免高基数 |
| `ontology_id` | 路由参数含 `ontology_id` 时提取;日志查询用它关联业务事件 |
| `status` / `duration_ms` | 响应状态码;全程耗时(进入中间件 → 响应完成) |
| `started_at` | 请求进入访问日志中间件的时刻;与 `timestamp` 配对:`timestamp − started_at ≈ duration_ms` |
| `client_ip` | `X-Forwarded-For` 首跳,无代理头则 socket 对端 |
| `user_agent` | 请求头原值,截断 200 字符;无头缺省 |
| `request_id` | 每请求唯一;接受客户端 `X-Request-ID` 透传(外部系统关联钩子) |
| `user_id` | 操作者 UUID;未认证请求落 `anonymous`,**永不为 null** |

### `ontology.import`(导入成功;source=http/cli 双入口同字段集)

`source`(http/cli)、`filename`、`format`、`size_bytes`、七段耗时、四个计数(class/property/instance/axiom)、`ontology_id`、`user_id`、`request_id`(CLI 恒 `-`)、`total_ms`。

分阶段耗时:

| 字段 | 测量点 |
|---|---|
| `read_ms` | 读取上传 body(CLI 为读本地文件) |
| `parse_ms` | RDF 解析(含语法校验) |
| `ir_ms` | `build_ir` 中间表示构建 |
| `store_ms` | 文件落盘 |
| `db_ms` | 重复名查询 + 行写入(两次 DB 往返之和,不含其间的 parse/IR) |
| `index_ms` | 索引构建 |
| `total_ms` | 业务整体 |

**残差口径**:`HTTP duration_ms − read_ms − total_ms` = 框架开销(multipart 流式解析、envelope 序列化等;缓冲 150MB body 计时不现实,不造假字段);`total_ms − 六段之和` = 杂项(hash、UUID、组装)。

### `ontology.import_failed`(level=error)

`source`、`filename`、`size_bytes`、`error_code`(envelope 错误码,如 `PARSE_FAILED`/`DUPLICATE_FILENAME`)、`error_type`(异常类名)、`user_id`、`request_id`。注:pyoxigraph 语法错误信息带行/列定位与出错片段(有界,便于定位)。

### `ontology.delete`(删除成功审计)

`request_id`、`user_id`、`ontology_id`、`filename`、`size_bytes`、`layout_deleted`(是否确有布局行被删)、`cache_evicted`(缓存是否确有条目被逐出)、`duration_ms`。删除为**物理删除**,按 store→db→layout→cache 四阶段执行。

### `ontology.delete_failed`(level=error)

`request_id`、`user_id`、`ontology_id`、`filename`、`failed_stage`(`store`/`db`/`layout`/`cache`)、`error_type`。可据此判断断在哪一步、之前哪些阶段已成功。

### `http.error`(异常处理器)

失败请求的结构化错误:`code`/`message`/`hint`/`method`/`path`/`request_id`/`user_id`,5xx 附堆栈。

### 第三方包装(`db.migrate`/`server.uvicorn`)

alembic/uvicorn 的纯文本行包装为 `message` + 公共字段。

## 脱敏原则

不记录:认证令牌、Cookie、完整请求体、本体敏感内容。`filename` 为用户输入,经 JSON 序列化器输出(控制字符必然转义,不会破坏行结构)。解析错误引用的出错行片段属定位必需,有界保留。

## 监控指标

Prometheus(`/metrics`):`ow_parse_seconds`(按 format 的解析直方图)、`ow_uploads_total`、`ow_cached_ontologies` 等。分位数(P50/P95/P99)经 Prometheus histogram 计算,不进日志。
