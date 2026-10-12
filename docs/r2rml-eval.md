# R2RML P1 验收(Ontop 实跑)

> **手工评测锚点,不进 CI。** R2RML 映射由 LLM 起草决策派生(类名/属性名非确定),
> 自动化会产生脆断言;本体侧结构(表→类、主键→subject 模板、FK→join)是确定性的,
> 由 `backend/tests/core/drafting/test_r2rml.py` 的 golden 测试在 CI 内钉死。本协议
> 人工验证「向导 → 存储 → 查看 → 导出 → Ontop 物化」全链路,输出物可直接喂 Ontop。

## 前置

| 项 | 要求 |
| --- | --- |
| JDK | ≥ 17(`java -version` 确认) |
| Ontop CLI | ≥ 5.x:下载 [ontop-cli zip](https://github.com/ontop/ontop/releases),解压后 `ontop` 可执行 |
| sqlite JDBC | Ontop 不自带:下载 [sqlite-jdbc](https://github.com/xerial/sqlite-jdbc/releases) 的 jar,放进 Ontop 的 `lib/` 或与 `ontop` 同目录 |
| sqlite3 | CLI 可用(建库用) |
| AI 设置 | 已配置 LLM(起草「生成」步骤需要;沿用 AI 对话线验证过的配置即可) |

## 步骤

### 1. 建库

复用金标库结构(`backend/tests/fixtures/golden_shop.sql`,8 表 7 FK,无种子数据),
补一张无主键的 `audit_log`(验证跳过逻辑)并插入种子行(物化需要数据):

```bash
rm -f /tmp/shop.db
sqlite3 /tmp/shop.db < backend/tests/fixtures/golden_shop.sql
sqlite3 /tmp/shop.db <<'SQL'
CREATE TABLE audit_log (event TEXT, at TEXT);
INSERT INTO audit_log VALUES ('login', '2026-10-12T09:00:00');
INSERT INTO "user" (id, username, email, role) VALUES
  (1, 'alice', 'alice@example.com', 'admin'),
  (2, 'bob',   'bob@example.com',   'user');
INSERT INTO customer (id, ref_user_id, name, vip) VALUES
  (1, 1, '张三', 0),
  (2, 2, '李四', 1);
INSERT INTO orders (id, customer_id, status, total, order_type, created_at) VALUES
  (101, 1, 'paid',   199.00, 'online', '2026-10-01T10:00:00'),
  (102, 2, 'pending', 58.50, NULL,     '2026-10-02T11:30:00');
SQL
```

(user 的列名以 fixture 为准:`username`/`email`/`role` 等;若插入报错,先
`sqlite3 /tmp/shop.db '.schema user'` 核对列名再调整。)

### 2. 向导起草

1. 先建连接:「数据库连接」页(侧栏菜单,AI 设置下方)→ 新建连接:
   引擎 `sqlite`、数据库 `/tmp/shop.db`(路径即 database 字段;host/port 留空)。
2. 文件 ▸ 新建 ▸ **从数据库起草本体…**:选刚才的连接 → 反射出 9 张表 → 全选 →
   生成 → 导入。「同时生成 R2RML 映射」开关默认开启,保持不动;
   `audit_log` 无主键,导入成功后 toast 会提示未入映射(预期行为)。

### 3. 导出两份文件

- 文件 ▸ 导出 ▸ **Turtle (.ttl)** → 得到本体(文件名形如 `shop<…>.ttl`);
- 文件 ▸ 导出 ▸ **R2RML 映射** → 得到映射文件(名字随向导的文件名,默认
  `shop-draft.r2rml.ttl`;下文以 `shop-draft.r2rml.ttl` 为准,改名了就替换)。
  无映射时 toast 指路,即步骤 2 没走。

顺手核对查看入口:Browse 顶栏「R2RML」按钮打开映射对话框——结构化对应表
(表 → 类、列 → 属性、FK → join)+ 跳过徽章 + 折叠的 Turtle 源码。

### 4. 写 db.properties

Ontop 侧的连接描述(与 Workbench 无关,新建文本文件即可):

```properties
jdbc.url=jdbc:sqlite:/tmp/shop.db
jdbc.driver=org.sqlite.JDBC
```

### 5. Ontop 物化

```bash
ontop materialize -m shop-draft.r2rml.ttl -p db.properties -o out.ttl
```

(sqlite-jdbc 的 jar 若没放进 `lib/`,加 `--jdbc` 目录参数或复制进去;报
`No suitable driver` 即驱动没就位。)

### 6. 断言

打开 `out.ttl` 逐条核对。物化是数据驱动的:只有播种的表产出三元组
(user/customer/orders/audit_log 各有数据,其余 5 表空属预期);列级属性来自
LLM 决策(非确定),故只断言确定性部分——IRI 模板、类型三元组、FK join 计数、跳过:

| # | 断言 | 判据 |
| --- | --- | --- |
| 1 | 非空 | `out.ttl` 有三元组(数十条量级;user 2 行 + customer 2 行 + orders 2 行的类型/属性/join) |
| 2 | customer 实例 IRI | 形如 `https://local/shop/customer/1`、`/customer/2`(subject 模板确定性:namespace `https://local/shop#` + 表名 + 主键列) |
| 3 | orders 实例 IRI | 形如 `https://local/shop/orders/101`、`/orders/102` |
| 4 | FK join | orders→customer 的引用属性三元组共 **2 条**(= orders 行数;护栏保证每条 FK 恰好一个对象属性,谓词局部名来自 LLM 决策,如 `hasCustomer`) |
| 5 | audit_log 无三元组 | 表里播了 1 行数据仍零三元组(全文搜 `audit_log` 零命中)——无主键被跳过的实证 |
| 6 | 类型三元组 | distinct `rdf:type` 恰好 **3 个类**(user/customer/orders;类名来自 LLM 决策,但每表一类是护栏钉死的) |

### 7.(可选)SPARQL 端点

```bash
ontop endpoint -m shop-draft.r2rml.ttl -p db.properties
```

浏览器开 `http://localhost:8080`,跑一条

```sparql
SELECT ?c (COUNT(?o) AS ?n) WHERE {
  ?o <https://local/shop#hasCustomer> ?c
} GROUP BY ?c
```

(谓词 IRI 以 out.ttl 实际产出为准替换)截图存档。

## 记录

> 通过 / 失败、Ontop 版本、三元组计数、踩坑——写在本节。验收后本节是 P2(受控编辑)
> 与 P3(漂移警告)的回归基线。
