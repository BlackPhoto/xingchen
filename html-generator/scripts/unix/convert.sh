#!/bin/bash
# ============================================================
# HTML → Word/PDF/Markdown 转换脚本 (macOS / Linux)
#
# 用法:
#   ./convert.sh --format docx --input report.html --output report.docx
#   ./convert.sh --format pdf --input report.html --output report.pdf
#   ./convert.sh --format md --input report.html --output report.md
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ===== 解析参数 =====
FORMAT=""
INPUT=""
OUTPUT=""
SKIP_CONFIRM=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --format)  FORMAT="$2";  shift 2 ;;
        --input)   INPUT="$2";  shift 2 ;;
        --output)  OUTPUT="$2"; shift 2 ;;
        --yes|-y)  SKIP_CONFIRM="1"; shift ;;
        *) echo "[ERROR] 未知参数: $1"; exit 1 ;;
    esac
done

if [[ -z "$FORMAT" || -z "$INPUT" || -z "$OUTPUT" ]]; then
    echo "用法: $0 --format {docx|pdf|md} --input <html文件> --output <输出文件>"
    exit 1
fi

if [[ ! -f "$INPUT" ]]; then
    echo "[ERROR] 输入文件不存在: $INPUT"
    exit 1
fi

# ===== 环境检测与准备 =====
setup_env() {
    # 优先用 conda
    if command -v conda &>/dev/null; then
        echo "[INFO] 检测到 conda，优先使用 conda 环境"
        local env_name="html-convert"
        if ! conda env list | grep -q "$env_name"; then
            echo "[INFO] 首次运行，正在创建 conda 环境 $env_name （约1分钟）..."
            conda create -n "$env_name" python=3.11 -y
        fi
        CONDA_RUN_PREFIX="conda run -n $env_name"
        # 检查并安装依赖
        if ! conda run -n "$env_name" python -c "import bs4, docx, lxml" 2>/dev/null; then
            echo "[INFO] 首次运行，正在安装依赖..."
            conda run -n "$env_name" pip install -r "$SCRIPTS_DIR/requirements.txt" --quiet
        fi
        # PDF 格式时检查 Playwright
        if [[ "$FORMAT" == "pdf" ]]; then
            if ! conda run -n "$env_name" python -c "import playwright" 2>/dev/null; then
                echo "[INFO] 正在安装 Playwright（含 Chromium 内核，约100MB）..."
                conda run -n "$env_name" pip install playwright --quiet
                conda run -n "$env_name" playwright install chromium 2>/dev/null || true
            fi
        fi
        echo "[INFO] conda 环境已就绪"
        return 0
    fi

    # 降级到 venv
    echo "[INFO] 使用 venv 环境"
    local env_path="$HOME/.html-convert-env"
    if [[ ! -f "$env_path/bin/activate" ]]; then
        echo "[INFO] 首次运行，正在创建 venv 并安装依赖（约1分钟）..."
        python3 -m venv "$env_path"
        source "$env_path/bin/activate"
        pip install -r "$SCRIPTS_DIR/requirements.txt" --quiet
        # PDF 格式时安装 Playwright
        if [[ "$FORMAT" == "pdf" ]]; then
            echo "[INFO] 正在安装 Playwright（含 Chromium 内核，约100MB）..."
            pip install playwright --quiet
            playwright install chromium 2>/dev/null || true
        fi
        echo "[INFO] 环境准备完成"
    else
        source "$env_path/bin/activate"
    fi
    CONDA_RUN_PREFIX=""
}

# ===== 执行 python 脚本 =====
run_python() {
    local script="$1"; shift
    if [[ -n "$CONDA_RUN_PREFIX" ]]; then
        $CONDA_RUN_PREFIX python "$script" "$@"
    else
        python "$script" "$@"
    fi
}

setup_env

# ===== Markdown：结构保真，直接转换（跳过影响分析确认） =====
# 说明：Markdown 只保留结构（标题/列表/表格/代码块），视觉样式天然不保留属预期行为。
# 结构降级（卡片→列表、时间线→有序列表等）由 Agent 场景中的 LLM 在转换前做精简版
# 影响分析并询问用户；入口脚本不重复交互确认，直接执行转换。
if [[ "$FORMAT" == "md" ]]; then
    echo "[INFO] Markdown 转换为结构保真，直接执行..."
    run_python "$SCRIPTS_DIR/html2md.py" "$INPUT" "$OUTPUT"
    echo "[OK] 转换完成: $OUTPUT"
    exit 0
fi

# ===== 转换前影响分析（docx/pdf）：只运行一次 --json 模式 =====
# 人类可读模式由 Agent 场景中的 LLM 负责呈现，脚本内不重复运行。
echo "[INFO] 正在分析转换影响..."

if [[ -n "${CONDA_RUN_PREFIX:-}" ]]; then
    JSON_RESULT=$($CONDA_RUN_PREFIX python "$SCRIPTS_DIR/impact_analyzer.py" "$INPUT" --format "$FORMAT" --json 2>/dev/null) || true
else
    JSON_RESULT=$(python "$SCRIPTS_DIR/impact_analyzer.py" "$INPUT" --format "$FORMAT" --json 2>/dev/null) || true
fi

NEED_REMIND=false
if [[ -n "$JSON_RESULT" ]]; then
    if echo "$JSON_RESULT" | grep -q '"need_remind": true'; then
        NEED_REMIND=true
        # 展示降级清单（供确认时参考）
        # 用 Python 解析 JSON 并逐行输出，兼容 macOS BSD sed 和 Linux GNU sed
        echo "[提醒] 检测到以下转换降级项："
        echo "$JSON_RESULT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for item in d.get('items', []):
        print('  - ' + item)
except Exception:
    pass
" || true
    fi
fi

if [[ "$NEED_REMIND" == "true" ]]; then
    if [[ -n "$SKIP_CONFIRM" ]]; then
        echo "[INFO] 检测到降级项，已通过 --yes 跳过确认"
    else
        echo "[提醒] 检测到转换降级项（详见上方），是否继续转换？"
        read -p "请确认 (y/n): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            echo "[INFO] 已取消转换"
            exit 0
        fi
    fi
fi

# ===== 执行转换 =====
echo "[INFO] 正在转换: $INPUT → $OUTPUT ($FORMAT)"

if [[ "$FORMAT" == "docx" ]]; then
    run_python "$SCRIPTS_DIR/html2docx.py" "$INPUT" "$OUTPUT"
elif [[ "$FORMAT" == "pdf" ]]; then
    run_python "$SCRIPTS_DIR/html2pdf.py" "$INPUT" "$OUTPUT"
fi

echo "[OK] 转换完成: $OUTPUT"