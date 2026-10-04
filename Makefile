# Ontology Workbench — 生命周期快捷方式
# ow serve 是单进程,同时提供 API 与构建后的 SPA(默认 8734)。
#   make setup  安装依赖(backend: uv sync;frontend: npm ci)
#   make dev    开发模式:后台 ow serve + 前台 vite dev(代理 /api → 8734)
#   make build  构建前端 dist(start 前需要;dev 模式不需要)
#   make start  后台启动 ow serve → http://127.0.0.1:8734/
#   make stop   停止 make start / make dev 托管的后台服务
# 端口与主机沿用 backend/.env(OW_HOST/OW_PORT);docker 部署走 docker-compose.yml,不经此文件。
# 端口探测基于 127.0.0.1(与 vite 代理一致),且只认环境变量里的 OW_PORT,.env 里的探测不到。

RUN_DIR  := .run
PID_FILE := $(RUN_DIR)/serve.pid
LOG_FILE := $(RUN_DIR)/serve.log
PORT     := $(if $(OW_PORT),$(OW_PORT),8734)

.PHONY: start stop dev setup build

# 裸 `make` 等于 make start
.DEFAULT_GOAL := start

start:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "already running (pid $$(cat $(PID_FILE))) — make stop first"; exit 1; \
	fi
	@if python3 -c "import socket; socket.socket().connect(('127.0.0.1', $(PORT)))" 2>/dev/null; then \
		echo "port $(PORT) is occupied by a process this Makefile does not manage (manual ow serve?)"; \
		echo "stop it first, or set OW_PORT and retry"; exit 1; \
	fi
	@mkdir -p $(RUN_DIR)
	@nohup sh -c 'echo $$$$ > $(PID_FILE); cd backend && exec .venv/bin/ow serve --no-browser' \
		</dev/null >$(LOG_FILE) 2>&1 &
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if python3 -c "import socket; socket.socket().connect(('127.0.0.1', $(PORT)))" 2>/dev/null; then break; fi; \
		if ! kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
			echo "serve exited during startup — tail of $(LOG_FILE):"; tail -5 $(LOG_FILE); \
			rm -f $(PID_FILE); exit 1; \
		fi; \
		sleep 0.5; \
	done; \
	echo "serving at http://127.0.0.1:$(PORT)/  (log: $(LOG_FILE))"

stop:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		pid=$$(cat $(PID_FILE)); kill $$pid; sleep 1; \
		if kill -0 $$pid 2>/dev/null; then \
			echo "pid $$pid still alive after TERM — it may be shutting down gracefully; verify with: ps -p $$pid"; \
		else \
			echo "stopped (pid $$pid)"; \
		fi; \
	else \
		echo "not running"; \
	fi; \
	rm -f $(PID_FILE)

dev:
	@mkdir -p $(RUN_DIR)
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "backend already up (pid $$(cat $(PID_FILE)))"; \
	elif python3 -c "import socket; socket.socket().connect(('127.0.0.1', $(PORT)))" 2>/dev/null; then \
		echo "port $(PORT) already serving (manual ow serve?) — reusing it; make stop will not manage it"; \
	else \
		nohup sh -c 'echo $$$$ > $(PID_FILE); cd backend && exec .venv/bin/ow serve --no-browser' \
			</dev/null >$(LOG_FILE) 2>&1 & \
		sleep 1; echo "backend up (pid $$(cat $(PID_FILE)); log $(LOG_FILE))"; \
	fi
	@cd frontend && npm run dev; status=$$?; \
	if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(PID_FILE)); rm -f $(PID_FILE); echo "backend stopped"; \
	fi; \
	exit $$status
# Ctrl-C 打断 dev 时收尾会被跳过:后端留存、pidfile 仍准确,make stop 可随时收掉;
# 再次 make dev 检测到存活 pid 会直接复用,不会重复起。

setup:
	cd backend && uv sync
	cd frontend && npm ci

build:
	cd frontend && npm run build
