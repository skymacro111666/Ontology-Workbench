<div align="center">

# Ontology Workbench

**探索、编辑、发布本体所需的一切——自托管,数据本地。**

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![简体中文](https://img.shields.io/badge/简体中文-当前-blue)](README.md)
[![English](https://img.shields.io/badge/English-README-gray)](assets/README/README.en.md)

[特性](#-特性亮点) · [快速开始](#-快速开始) · [功能巡礼](#-功能巡礼) · [许可证](#-许可证)

</div>

自托管的开源本体工作台——"本体的 IDE"。部署在你自己的机器上,浏览器访问:上传 OWL 本体即可浏览、可视化、**编辑**,并一键导出可直接部署的静态文档站。本体数据永远不离开你的服务器。

## ✨ 特性亮点

- **三区阅读工作区** —— 类树 / 属性 / 前缀侧栏 + 即时搜索 + 面包屑谱系,大本体虚拟滚动不卡顿
- **实体详情三态视图** —— 详情 / 分屏 / 纯图一键切换,反向引用面板回答"谁在引用我"
- **图可视化** —— G6 画布承载局部邻居图与全局总览,边按语义着色,节点位置拖拽后持久化
- **画布内编辑** —— 右键即可新建 / 编辑 / 删除类与属性,连反向引用一并清理,乐观锁防冲突
- **源码编辑** —— CodeMirror 驱动的 Turtle 编辑器,搜索替换、脏态守卫、试解析后才落盘
- **一键文档站导出** —— 零外部依赖的静态站,扔给 GitHub Pages 即可发布
- **工程化内核** —— JSON 结构化日志、Prometheus 指标、`ow` CLI 三命令,上传导出直接进 CI

## 🚀 快速开始

### 方式一:Docker(推荐)

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench
docker compose up -d --build
```

访问 `http://127.0.0.1:8734`。数据落在项目内 `./data` 与 `./logs`,容器重建不丢失;`OW_PORT=9000 docker compose up -d` 可换端口,`OW_JWT_SECRET` 不设则首次启动自动生成并存在 `data/jwt-secret`。

### 方式二:源码部署

前置:Python ≥ 3.11 与 [uv](https://docs.astral.sh/uv/);Node.js ≥ 22 与 npm。

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

首次访问引导创建管理员(一次性),登录后载入内置示例本体即可体验。**配置优先级:CLI 参数 > 环境变量(`.env`)> 默认值**;常用变量 `OW_HOST` / `OW_PORT` / `OW_DATA_DIR` / `OW_DB_URL`(默认 SQLite,可切 PostgreSQL)/ `OW_LOG_LEVEL`。

## 🧭 功能巡礼

### 🗂 主工作区:三区布局

<!-- 截图占位: assets/README/screenshots/browse-tree.png -->

- **顶栏**:本体标题 + 即时搜索(防抖 150ms,按标签 / 本地名 / 注释做大小写不敏感子串匹配)+ 总览图入口 + 导出按钮
- **左侧栏**:统计摘要头("101 类 · 38 属性")+ 三个标签页——**类**(`rdfs:subClassOf` 层级树,虚拟滚动 + 懒加载)、**属性**(对象 / 数据属性)、**前缀**(prefix ↔ IRI 对照)
- **内容区**:面包屑谱系(`schema:Thing › Person`)标示层级位置;状态栏实时显示文件名、类 / 属性数、triples 数与解析耗时

### 🔍 实体详情:三态视图

<!-- 截图占位: assets/README/screenshots/browse-backrefs.png -->

每个实体(类 / 对象属性 / 数据属性)支持三种视图:

1. **详情态**——多语言标签、注释、父子类、反向引用面板("谁引用我",反向索引驱动)与**原始 TTL**(复杂公理按原始 Turtle 片段展示)
2. **分屏态**——左侧局部邻居图 + 右侧详情并排,边看图边读
3. **纯图态**——局部邻居图全幅铺开

<!-- 截图占位: assets/README/screenshots/browse-split.png -->

### 🕸 图可视化

<!-- 截图占位: assets/README/screenshots/graph-overview.png -->

G6 画布服务两种数据源:详情页的**局部邻居图**与全局**总览图**(点击节点直达详情)。边按语义编码:`subClassOf` 紫色虚线、对象属性青色实线、数据属性灰色点线;节点徽章显示直接子类数;控制栏提供缩放、边标签开关与类型过滤。**大本体降级**:总览超过 500 节点自动只显示顶层 3 层;**节点位置持久化**:拖拽布局保存在服务端,下次打开原样呈现,「重排」一键恢复自动布局。

### ✏️ 画布内编辑

<!-- 截图占位: assets/README/screenshots/graph-context-menu.png -->

在图上右键:空白处新建类;类节点上新建子类 / 对象属性 / 数据属性(domain 自动预填)、编辑、删除。弹窗内选择前缀、父类、range(对象属性选类,数据属性选 XSD 类型);删除默认 **prune**——连子类继承、属性 domain/range、实例类型等反向引用一并清理。所有写操作带 **baseFileHash 乐观锁**,文件在别处被改过则拒绝并提示刷新。

<!-- 截图占位: assets/README/screenshots/entity-dialog.png -->

### 📝 源码编辑

<!-- 截图占位: assets/README/screenshots/source-edit.png -->

文本视图即编辑器:CodeMirror 语法高亮、查找替换(Ctrl+F 或工具栏按钮)、脏态标记与切换守卫(保存 / 放弃 / 取消)。保存前服务端**试解析**,语法错误原样拒绝、文件零损伤;与画布编辑共用同一套乐观锁管线。

### 📤 文档站导出

<!-- 截图占位: assets/README/screenshots/export.png -->

`/export` 页面、`POST /api/ontologies/{id}/export/site` 与 `ow export-site <id>` 走同一导出路径,输出**零外部依赖**的静态站:

```
{out}/
├── index.html            # 总览:统计、前缀表、顶层类入口
├── entities/{hash}.html  # 每实体一页(标签/注释/父子/属性/公理)
├── data/index.json       # 静态搜索索引(curie/label/eid → 页面)
└── site.css / site.js    # 原生 JS:树导航 + 客户端搜索
```

输出目录可直接部署到 GitHub Pages 或任意静态服务器;目标非空时拒绝覆盖(换 `--out` 或显式 `--force`)。

### 📥 上传与示例本体

<!-- 截图占位: assets/README/screenshots/home.png -->

拖拽上传 Turtle(`.ttl`)/ RDF-XML(`.owl` / `.rdf`)/ JSON-LD(`.jsonld`),单文件 ≤ 150MB,格式按扩展名 + 内容双重嗅探;内置 **Pizza / Wine / FOAF** 示例本体一键载入。



## 📄 许可证

[Apache License 2.0](LICENSE) · Copyright 2026 The Ontology Workbench Authors.
