# Ontology Workbench

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**自托管的本体工作台("本体的 IDE")**:部署在你自己的机器上,浏览器访问;上传 OWL 本体即可浏览、理解、可视化,并一键导出可直接部署的静态文档站。Phase 1 专注"读"侧——单用户、源码部署、真开源(Apache-2.0);本体数据永远不离开你的服务器。

## 功能巡礼

### 主工作区:三区阅读布局

打开本体后进入 `/browse` 主工作区:

- **顶栏**:本体标题 + 即时搜索框(防抖 150ms,按标签 / 本地名 / 注释做大小写不敏感的子串匹配)+ 总览图入口 + 导出按钮。
- **左侧栏**:顶部统计摘要头("101 类 · 38 属性"),下方三个标签页——**类**(按 `rdfs:subClassOf` 层级树,虚拟滚动 + 懒加载,大本体不卡)、**属性**(对象 / 数据属性列表)、**前缀**(prefix ↔ IRI 对照表)。
- **内容区**:面包屑类谱系(`schema:Thing › Person`)标示当前层级位置;底部状态栏实时显示文件名、类 / 属性数、triples 数与解析耗时。

### 实体详情:三态视图

每个实体(类 / 对象属性 / 数据属性)的详情支持三种视图切换:

1. **详情态**——多语言标签、注释、父 / 子类、挂载属性表,以及特色的双面板:**反向引用面板**("谁引用我",反向索引驱动)与**原始 TTL**(复杂公理按原始 Turtle 片段显示)。
2. **分屏态**——左侧局部邻居图 + 右侧详情并排,边看图边读文档。
3. **纯图态**——局部邻居图(父 / 子 / 兄弟 / 关联属性)全幅铺开。

### 图可视化

一个 React Flow 组件服务两种数据源:详情页的**局部邻居图**与独立 `/graph` 页的**全局总览图**(点击节点直达详情,局部图提供"在总览中查看"回链)。边采用语义编码:`subClassOf` 紫色虚线、对象属性青色实线、数据属性灰色点线;节点徽章显示直接子类数,画布控制栏提供缩放、边标签开关与类型过滤。**大本体降级**:总览节点超过 500 时自动只显示顶层 3 层并给出提示,避免浏览器卡死。

### 上传与示例本体

浏览器拖拽上传 Turtle(`.ttl`)/ RDF-XML(`.owl` / `.rdf`)/ JSON-LD(`.jsonld`),单文件 ≤ 150MB,格式按扩展名 + 内容双重嗅探;内置 **Pizza / Wine / FOAF** 三个示例本体,一键载入,首屏零门槛。

## 文档站导出

`/export` 页面按钮、`POST /api/ontologies/{id}/export/site` 与 `ow export-site <id>` 走同一条导出路径,输出**零外部依赖**(无 CDN、无框架 JS)的静态站:

```
{out}/
├── index.html            # 总览:统计、前缀表、顶层类入口
├── entities/{hash}.html  # 每实体一页(标签/注释/父子/属性/公理)
├── data/index.json       # 静态搜索索引(curie/label/eid → 页面)
├── data/entities.json    # eid → 页面映射
└── site.css / site.js    # 原生 JS:树导航 + 客户端搜索(~200 行)
```

输出目录可直接扔给 GitHub Pages 或任意静态服务器;导出器复用与 API 相同的 IR,同一份解析、双消费者。目标目录非空时拒绝覆盖(换 `--out` 或显式 `--force`):

```bash
uv run ow export-site <ontology-id> --out ./gh-pages
```

## 快速开始(源码部署)

前置:Python ≥ 3.11 与 [uv](https://docs.astral.sh/uv/);Node.js ≥ 22 与 npm。

```bash
git clone https://github.com/<you>/ontology-workbench.git
cd ontology-workbench

# 1) 后端依赖
cd backend && uv sync

# 2) 前端构建(SPA 产物由后端同端口服务)
cd ../frontend && npm ci && npm run build

# 3) 启动(回环地址 + 交互终端时自动打开浏览器;--no-browser 关闭)
cd ../backend && uv run ow serve
```

访问 `http://127.0.0.1:8734`:首次启动引导创建管理员(一次性,此后永久关闭),登录后载入示例本体即可体验。首次运行自动从 `.env.example` 生成 `backend/.env`(`OW_JWT_SECRET` 自动生成写回)。

**配置优先级:CLI 参数 > 环境变量(`.env`)> 默认值**。常用变量:`OW_HOST` / `OW_PORT` / `OW_DATA_DIR` / `OW_LOG_DIR` / `OW_DB_URL`(默认 SQLite,可切 PostgreSQL)/ `OW_LOG_LEVEL`。端口被占用时自动 +1 重试(至多 10 个);非回环绑定时启动会向 stderr 输出警告,建议置于反向代理 / HTTPS 之后。

## 工程化与可观测性

- **CLI 三命令**:`ow serve`(单进程服务 API + SPA)/ `ow import PATH`(服务器端导入,与浏览器上传同路径)/ `ow export-site ID`(无 UI 导出)——上传与导出均可脚本化,可直接进 CI / GitHub Actions。
- **认证**:JWT bearer;密码 argon2id 哈希;token 7 天有效。
- **可观测性**:structlog 结构化日志(全环境统一 JSON lines,stdout + 文件双写,按天轮转保留 15 天,事件名 `模块.动作`);`GET /metrics` 暴露 Prometheus 指标(HTTP 指标 + 解析耗时 / 上传计数 / 缓存数,免认证供采集器抓取);每请求 `X-Request-ID` 贯穿响应头、响应体与日志。

## 与竞品对比

| 维度 | Ontology Workbench | [Competitor A](https://competitor-a.example) | Competitor B |
|------|--------------------|--------------------|--------------------|
| 自托管与隐私 | ✅ 自托管,本体不出你的服务器 | ❌ 托管服务,本体上传第三方 | ✅ 浏览器端运行,数据本地 |
| 许可证 | ✅ Apache-2.0(可审计 / 可商用 / 可贡献) | ❌ 闭源(托管免费,桌面版收费) | ⚠️ BSL 1.1(限制生产商用,2030 转 Apache 2.0) |
| 文档站导出 | ✅ 一键静态站,可直接部署 GitHub Pages | ❌ 无 | ❌ 无 |
| CLI / CI 集成 | ✅ `ow import` / `ow export-site` + `/metrics` | ❌ 无 | ❌ 无 |
| 技术栈 | FastAPI + rdflib + SQLite/PG;React 19 + AntD v6 SPA | 闭源托管 | Streamlit + rdflib(交互全页刷新,体验上限低) |

Competitor A 与 Competitor B 验证了需求,也定义了基线:隐私敏感场景要"你的本体你的站",工程团队要许可证与脚本化——这正是 Ontology Workbench 的位置。

## 已知限制(Phase 1)

- **只读**:全部编辑能力后置(Phase 2 起步);无 SHACL / 推理 / SPARQL 控制台 / 个体展示。
- **单用户**:多用户与数据隔离的后端骨架已就绪,管理界面 Phase 2 提供。
- **仅渲染 OWL 实体**:Phase 1 只展示 `owl:Class` / `owl:ObjectProperty` / `owl:DatatypeProperty` 实体;纯 SKOS(如 `skos:Concept` / `skos:broader`)或其他无 OWL 类的本体,类树为空。SKOS 支持属 Phase 2。
- **大本体**:> 50MB 上传给警告但尝试解析;总览图 > 500 节点降级为顶层 3 层。

## Overview (English)

Ontology Workbench is a self-hosted, open-source (Apache-2.0) workbench for reading and documenting OWL ontologies — an "IDE for ontologies" that runs on your own server. Upload Turtle / RDF-XML / JSON-LD, browse through a class tree with instant search, switch between detail / split / graph views, explore local-neighbor and global-overview React Flow graphs, then export a deployable static docs site in one command.

```bash
# from a fresh clone
cd backend && uv sync
cd ../frontend && npm ci && npm run build
cd ../backend && uv run ow serve   # http://127.0.0.1:8734
```

Differentiators versus hosted/closed-source [Competitor A](https://competitor-a.example) and BSL-1.1-licensed Competitor B (see the matrix above): self-hosted privacy, a true open-source license, one-command docs-site export, and CI-friendly `ow` CLI plus Prometheus `/metrics` and JSON structured logs. Phase 1 is read-only and single-user; editing and multi-user land in Phase 2.

## 许可证 / License

[Apache License 2.0](LICENSE) · Copyright 2026 The Ontology Workbench Authors.
