<div align="center">

# Ontology Workbench

**自托管的开源本体工作台，探索、编辑、发布本体**

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![简体中文](https://img.shields.io/badge/简体中文-README-blue)](README.md)
[![English](https://img.shields.io/badge/English-README-gray)](assets/README/README.en.md)

[特性](#-特性亮点) · [快速开始](#-快速开始) · [许可证](#-许可证)

</div>

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

## 📄 许可证

[Apache License 2.0](LICENSE) · Copyright 2026 The Ontology Workbench Authors.
