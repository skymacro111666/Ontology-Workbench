# AI 起草评测协议(金标库)

> **手工评测锚点,不进 CI。** 本文档与 `backend/tests/fixtures/golden_shop.sql`、
> `backend/tests/core/drafting/test_golden_reflect.py` 三者绑定:改金标库的清单
> (表数 / FK 数 / UNIQUE 列)必须三处同步。CI 只验反射清单;LLM 生成质量由
> 本协议人工评测(模型输出非确定,自动化会产生脆断言)。

## 金标库清单(8 表 / 7 FK)

| 表 | 期望类(labelLanguage=zh) | 说明 |
| --- | --- | --- |
| `customer` | 客户 | `vip` 布尔、`name` 字符串 |
| `orders` | 订单 | `status` 非空枚举串、`order_type` 可空、`total` 金额 |
| `order_items` | 订单项 | 双 FK(orders/product),数量+单价 |
| `product` | 产品 | `sku` UNIQUE、`price` 金额、`status` 可空 |
| `category` | 类目 | 无 FK,自成一表 |
| `address` | 地址 | `address_type` 可空枚举、`is_default` 布尔 |
| `payment` | 支付 | `pay_type` 枚举、`amount` 金额、`paid_at` 时间 |
| `user` | 用户 | `username`/`email` UNIQUE、`role` 枚举 |

**期望对象属性(每个 FK 一个,≥ 7):**

| FK | 期望连接(方向不限) |
| --- | --- |
| `orders.customer_id → customer` | 订单 ⇄ 客户 |
| `order_items.order_id → orders` | 订单项 ⇄ 订单 |
| `order_items.product_id → product` | 订单项 ⇄ 产品 |
| `product.category_id → category` | 产品 ⇄ 类目 |
| `address.customer_id → customer` | 地址 ⇄ 客户 |
| `payment.order_id → orders` | 支付 ⇄ 订单 |
| `customer.ref_user_id → user` | 客户 ⇄ 用户 |

**数据属性抽查表(8 项):** `customer.name`(string)、`customer.vip`(boolean)、
`product.sku`(string)、`product.price`(decimal)、`orders.status`(string)、
`orders.total`(decimal)、`orders.created_at` 或 `payment.paid_at`(dateTime)、
`user.email`(string)。

## 验收阈值

| 项 | 阈值 |
| --- | --- |
| 类数量 | 8/8 表全覆盖,每类 label 中文非空 |
| 对象属性 | ≥ 7,每个 FK 恰好一个,domain/range 连接正确的两个类 |
| 数据属性 | 抽查 8 项 ≥ 6 项存在且 datatype 合理 |
| 合并质量 | 无重复类名;FK 补全覆盖全部 7 条 |
| 护栏 | 导入 TTL lint 无 error 级发现(missing-label 之类 warning 可接受) |
| 记录 | stats 全字段粘贴:classCount / objectPropertyCount / dataPropertyCount / elapsedMs / in·out tokens / batchCount |

## 手工流程(runbook)

1. **建库**:`sqlite3 /tmp/golden_shop.db < backend/tests/fixtures/golden_shop.sql`
2. **启动**:后端 `cd backend && uv run ow serve`,前端走已构建 dist(或 `npm run dev`)
3. **AI 配置**:右上菜单 → AI 设置;「测试连接」应显示延迟毫秒数
4. **走向导**:新建 ▸ 从数据库起草 → SQLite、路径 `/tmp/golden_shop.db` →
   读取表结构(应见 8 表、注释为空、FK 徽章)→ 保持全选 → 生成草稿,
   观察批次进度条(金标库单批应 `第 1/1 批`)
5. **预览核对**:对照上方三类清单逐项打勾;TTL 预览可读、含 `owl:Class`/
   `owl:ObjectProperty`/`owl:DatatypeProperty` 三类公理
6. **拒绝级联**:反选一个类(如 `Category`)→ 导入 → 导入体应把它列入
   `rejectedClassNames`,生成的本体里无该类及其属性
7. **落地核对**:跳转 `/browse/{id}` 画布;Home 卡片带「AI 起草」徽章;
   Registry 记录 origin=agent
8. **粘贴结果**:把向导 stats、lint 发现与抽查勾选表贴进下述模板存档

### 结果记录模板

```
日期:____  模型:____(provider/baseUrl/model)
类 8/8?__  对象属性 __/7  数据抽查 __/8
stats: classCount=__ objectPropertyCount=__ dataPropertyCount=__
       elapsedMs=__ tokens in/out=__/__ batchCount=__
lint: ______
反选级联测试:通过 / 未通过(现象:____)
备注:____
```

## 与 CI 的边界

- `test_golden_reflect.py` 只断言**反射清单**(表 8、FK 7、UNIQUE/枚举抽查列)——确定性,进 CI。
- 本文档的生成质量阈值依赖真实模型,输出非确定,**任何情况下不得写成 CI 断言**;
  新增自动化前先更新本文件说明边界。
