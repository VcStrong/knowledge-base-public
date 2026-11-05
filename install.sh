#!/bin/bash
# From 大大王.DT
# 知识库一键安装：建 Python 环境、初始化空知识库、加 kb 命令、接入 Claude Code。可重复运行。
# 用法：./install.sh [--autostart] [--no-mcp] [--no-alias]
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
AUTOSTART=0; MCP=1; ALIAS=1
for a in "$@"; do
  case "$a" in
    --autostart) AUTOSTART=1 ;;
    --no-mcp) MCP=0 ;;
    --no-alias) ALIAS=0 ;;
    -h|--help) sed -n 2,3p "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 1 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

echo "知识库安装：${DIR}"

# 1. 系统与 Python
[ "$(uname)" = Darwin ] || warn "当前不是 macOS：钥匙串、系统通知、Word 转文字等功能不可用"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  p=$(command -v "$c" 2>/dev/null) || continue
  if "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then PY=$p; break; fi
done
[ -n "${PY}" ] || die "需要 Python 3.9 以上（建议：brew install python）"
ok "Python：$("${PY}" --version 2>&1)（${PY}）"

# 2. 虚拟环境与依赖
VENV="${DIR}/_system/.venv"
if [ ! -x "${VENV}/bin/python" ]; then
  "${PY}" -m venv "${VENV}" || die "建虚拟环境失败"
fi
"${VENV}/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
"${VENV}/bin/python" -m pip install -q -r "${DIR}/_system/requirements.txt" || die "安装依赖失败（需要能访问 PyPI）"
ok "依赖已安装：$(tr '\n' ' ' < "${DIR}/_system/requirements.txt")"
"${VENV}/bin/python" - <<'PY' || die "这个 Python 的 SQLite 不支持全文检索（FTS5），请换用 Homebrew 的 Python"
import sqlite3
sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)')
PY
ok "SQLite 全文检索可用"

# 3. 初始化空知识库（已有数据不会动）
chmod +x "${DIR}/kb"
"${DIR}/kb" init >/dev/null
ok "知识库目录已就绪（期/、收件箱/、索引）"

# 4. kb 命令
if [ "${ALIAS}" = 1 ]; then
  case "${SHELL:-}" in */bash) RC="${HOME}/.bash_profile" ;; *) RC="${HOME}/.zshrc" ;; esac
  touch "${RC}"
  LINE="alias kb=\"${DIR}/kb\""
  if grep -q '^alias kb=' "${RC}"; then
    if grep -qxF "${LINE}" "${RC}"; then ok "kb 命令已在 ${RC}"
    else
      cp "${RC}" "${RC}.bak-kb"
      grep -v '^alias kb=' "${RC}.bak-kb" > "${RC}"; echo "${LINE}" >> "${RC}"
      ok "已更新 ${RC} 里的 kb 命令（旧文件备份为 ${RC}.bak-kb）"
    fi
  else
    printf '\n# 本地知识库\n%s\n' "${LINE}" >> "${RC}"; ok "已在 ${RC} 加入 kb 命令（新开终端生效）"
  fi
fi

# 5. 接入 Claude Code（用户级 MCP，所有目录可用）
CLAUDE=$(command -v claude || true)
for c in /opt/homebrew/bin/claude /usr/local/bin/claude "${HOME}/.local/bin/claude"; do [ -n "${CLAUDE}" ] || { [ -x "$c" ] && CLAUDE=$c; }; done
if [ "${MCP}" = 1 ]; then
  if [ -n "${CLAUDE}" ]; then
    "${CLAUDE}" mcp remove kb -s user >/dev/null 2>&1 || true
    "${CLAUDE}" mcp add kb -s user -- "${VENV}/bin/python" "${DIR}/_system/kb.py" serve >/dev/null && ok "已接入 Claude Code（MCP 服务 kb，用户级）"
  else
    warn "没找到 claude 命令：装好 Claude Code 后重新运行 ./install.sh 接入知识库"
  fi
fi

# 6. 开机自动启动网页（可选）
if [ "${AUTOSTART}" = 1 ]; then
  PL="${HOME}/Library/LaunchAgents/com.local.kb.web.plist"
  mkdir -p "$(dirname "${PL}")"
  cat > "${PL}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local.kb.web</string>
  <key>ProgramArguments</key><array><string>${DIR}/kb</string><string>web</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "${CLAUDE:-/usr/bin/true}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${DIR}/_system/web.log</string>
  <key>StandardErrorPath</key><string>${DIR}/_system/web.log</string>
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)" "${PL}" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "${PL}" && ok "网页已设为登录后自动启动（http://127.0.0.1:11555）"
fi

# 7. 其他检查
command -v git >/dev/null && ok "git 可用" || warn "没有 git：代码仓库索引、开发分支识别不可用（xcode-select --install）"

cat <<TXT

安装完成。接下来：
  1. 新开一个终端（或 source ~/.zshrc），运行  kb  看总览
  2. kb web  打开网页 http://127.0.0.1:11555（「📖 文档」里有使用说明）
  3. 在 Claude Code 里执行 /mcp，确认 kb 已连接
  4. 登录要抓取的系统（凭据存本机钥匙串）：
       kb login confluence.example.com <用户名>
       kb login figma.com token
  5. 登记代码仓库（可选）：kb repo <仓库路径> [名称]
TXT
