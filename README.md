<div align="center">

# Ontology Workbench

**自托管的开源本体工作台，探索、编辑、发布本体**

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![简体中文](https://img.shields.io/badge/简体中文-README-blue)](README.md)
[![English](https://img.shields.io/badge/English-README-gray)](assets/README/README.en.md)

[特性](#-特性亮点) · [功能展示](#-功能展示) · [快速开始](#-快速开始) · [MCP](#mcp) · [许可证](#-许可证)

</div>

## ✨ 特性亮点

- **三区协同浏览** —— 类树、属性、前缀URI侧栏+即时搜索，大本体下虚拟滚动丝滑无卡顿
- **智能图可视化** —— 画布承载局部邻居图与全局总览,边按语义着色,节点位置拖拽后持久化记忆
- **画布即点即编** —— 右键完成类与属性的新建、编辑、删除，无需跳转多页面
- **大本体渐进画布** —— 存活类过 2000 时总览自动切折叠根视图(点 +/− 徽章就地展开子树,子树大小实时可见),可随时切回全图
- **毫秒级增量提交** —— 编辑即时补丁内存索引,读写所见即所得;文件由后台防抖落盘
- **集成源码编辑** —— 内置编辑器,搜索替换功能全覆盖
- **内置 SPARQL 查询台** —— 浏览页第三视图,只读查询引擎级强制(UPDATE 一律拒绝),SELECT/ASK/CONSTRUCT 三形态结果,IRI 自动缩写为 curie
- **SHACL 校验** —— 加载内置或自定义 SHACL shapes,对本体运行标准一致性校验,三档严重度报告
- **OWL 2 compatible & profile-aware** —— Manchester 公理渲染与 EL/QL/RL/DL profile 检测(词表级近似)
- **离线文档导出** —— 生成完全零外部依赖的静态站点

## 📸 功能展示

**概览页面** 

![概览首页](assets/README/screenshots/home.png)


**图形模式** 

![工作区图形模式](assets/README/screenshots/browser-graph.png)

**源码编辑** 

![源码模式](assets/README/screenshots/browser-text.png)


## 🚀 快速开始

### 方式一:Docker(推荐)

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench
docker compose up -d --build
```

访问 `http://<你的IP地址>:8734`。数据保存在项目内 `./data` 与 `./logs` 目录中,容器重建不丢失。`OW_PORT=9000 docker compose up -d` 可设置端口,`OW_JWT_SECRET` 不设则首次启动自动生成并保存在 `data/jwt-secret`。

### 方式二:源码部署

前置需求:Python ≥ 3.11、uv、Node.js ≥ 22 和 npm。

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench

# 1) 后端依赖
cd backend && uv sync

# 2) 前端构建(SPA 产物由后端同端口服务)
cd ../frontend && npm ci && npm run build

# 3) 启动(回环地址 + 交互终端时自动打开浏览器;--no-browser 关闭)
cd ../backend && uv run ow serve
```

访问 `http://<你的IP地址>:8734`(需先在 `.env` 设 `OW_HOST=0.0.0.0`,默认仅监听回环地址),首次访问引导创建管理员(一次性),登录后载入内置示例本体即可体验。**配置优先级:CLI 参数 > 环境变量(`.env`)> 默认值**;常用变量 `OW_HOST` / `OW_PORT` / `OW_DATA_DIR` / `OW_DB_URL`(默认 SQLite,后续支持 PostgreSQL)/ `OW_LOG_LEVEL`;文档站导出目录默认限定在 `{数据目录}/exports/` 下,自托管可设 `OW_EXPORT_ALLOW_ANY_PATH=1` 放开。

## MCP

自带 MCP 服务器:10 个工具、streamable HTTP 传输,挂在 `/api/v1/mcp/`(URL 以尾斜杠结尾)。创建首枚 Agent 令牌后重启服务即完成挂载;令牌清零后重启则端点消失(404)。

### 创建 Agent 令牌

两种方式:

- **1、设置页**:顶栏用户菜单 → Agent 令牌
- **2、API**:

```bash
curl -X POST http://127.0.0.1:8734/api/v1/agent-tokens \
  -H "Authorization: Bearer <登录 token>" -H "Content-Type: application/json" \
  -d '{"label":"agent"}'
```

明文令牌仅在创建响应中展示一次;另有 `OW_AGENT_TOKENS="label:owag_xxxxxx"` 供首次启动批量导入(迁移用,之后以数据库为准)。

### 客户端接入

```bash
claude mcp add --transport http ow http://127.0.0.1:8734/api/v1/mcp/ \
  --header "Authorization: Bearer owag_xxxxxx"
```

或任意支持 streamable HTTP 的 MCP 客户端:

```json
{
  "mcpServers": {
    "ow": {
      "type": "http",
      "url": "http://127.0.0.1:8734/api/v1/mcp/",
      "headers": { "Authorization": "Bearer owag_xxxxxx" }
    }
  }
}
```

### 工具一览

| 工具 | 说明 |
|------|------|
| `list_ontologies` | 入口工具:oid/标题/实体计数/profile |
| `get_ontology` | 元数据:统计、前缀表、OWL 2 profile、保存状态 |
| `search_entities` | curie/label/comment 三字段搜索,kind 过滤 |
| `get_entity` | 标签/注释/Manchester 公理行/被引用/实例数 |
| `get_class_tree` | 类树切片,指定父类逐层下钻 |
| `get_instances` | 类下实例清单(含断言) |
| `run_lint` | 内置 10 规则 + 自定义 SPARQL 规则 |
| `run_validation` | SHACL 校验(未配置 shapes 时返回指路错误) |
| `sparql_query` | 只读 SPARQL(引擎级强制,1000 行截断) |
| `export_file` | 全文导出(200,000 字节截断,超限建议改用 sparql_query) |

安全语义:Agent 令牌是账户的机器凭证(GitHub PAT 同构)——数据库仅存哈希、可直接作 REST Bearer 凭证、受只读端点允许清单约束,吊销即时生效。

## 📄 许可证

[Apache License 2.0](LICENSE) · Copyright 2026 The Ontology Workbench Authors.
