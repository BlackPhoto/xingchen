#!/bin/bash
# ============================================================
# TeleAgent Database Health Check Script (macOS / Linux)
# Checks scheduler.db and im-service.db integrity.
# Uses Python (TeleAgent bundled or system) for SQLite operations.
# ============================================================
set -e

# ============================================================
# Path Resolution
# ============================================================

get_teleagent_data_dir() {
    # Priority: environment variable
    if [ -n "$TELEAGENT_DATA_DIR" ] && [ -d "$TELEAGENT_DATA_DIR" ]; then
        echo "$TELEAGENT_DATA_DIR"
        return 0
    fi
    # Owner marker: read current-owner.json ownerDir → users/<owner>/
    local owner_file="$HOME/.local/share/TeleAgent/current-owner.json"
    if [ -f "$owner_file" ]; then
        local owner
        owner=$(python3 -c "import json;print(json.load(open('$owner_file')).get('ownerDir',''))" 2>/dev/null || echo "")
        if [ -n "$owner" ] && [ -d "$HOME/.local/share/TeleAgent/users/$owner" ]; then
            echo "$HOME/.local/share/TeleAgent/users/$owner"
            return 0
        fi
    fi
    # Standard path (legacy root)
    local standard_path="$HOME/.local/share/TeleAgent"
    if [ -d "$standard_path" ]; then
        echo "$standard_path"
        return 0
    fi
    return 1
}

get_teleagent_python() {
    local data_dir data_root
    data_dir="$(get_teleagent_data_dir)" || true
    if [ -n "$data_dir" ]; then
        # 内置 runtime 位于实际数据根（账号目录上一级：…/TeleAgent/users/<账号> → …/TeleAgent）
        data_root="$(dirname "$(dirname "$data_dir")")"
        # macOS bundled python（数据根）
        local py_root="$data_root/runtimes/python/bin/python3"
        if [ -x "$py_root" ]; then
            echo "$py_root"
            return 0
        fi
        local py_alt_root="$data_root/runtimes/python/bin/python"
        if [ -x "$py_alt_root" ]; then
            echo "$py_alt_root"
            return 0
        fi
        # 旧位置兜底（兼容老版本结构）
        local py_mac="$data_dir/runtimes/python/bin/python3"
        if [ -x "$py_mac" ]; then
            echo "$py_mac"
            return 0
        fi
        # Alternative: python symlink
        local py_alt="$data_dir/runtimes/python/bin/python"
        if [ -x "$py_alt" ]; then
            echo "$py_alt"
            return 0
        fi
    fi
    # Fallback to system python3
    if command -v python3 &>/dev/null; then
        echo "$(command -v python3)"
        return 0
    fi
    if command -v python &>/dev/null; then
        echo "$(command -v python)"
        return 0
    fi
    return 1
}

# ============================================================
# Main
# ============================================================

echo ""
echo "========================================"
echo " TeleAgent Database Health Check (macOS / Linux)"
echo "========================================"
echo ""

# Locate data directory
DATA_DIR="$(get_teleagent_data_dir)" || {
    echo "[ERROR] TeleAgent data directory not found."
    echo "  Standard path: \$HOME/.local/share/TeleAgent"
    echo "  Or set TELEAGENT_DATA_DIR environment variable."
    exit 1
}
echo "[INFO] Data directory: $DATA_DIR"

# Locate Python
PYTHON="$(get_teleagent_python)" || {
    echo "[ERROR] No Python found. Neither TeleAgent Python runtime nor system Python available."
    exit 1
}
echo "[INFO] Python: $PYTHON"

# Define database paths
SCHEDULER_DB="$DATA_DIR/scheduler/scheduler.db"
IM_SERVICE_DB="$DATA_DIR/im-service/im-service.db"
# 使用跨平台兼容的临时文件创建方式
# macOS BSD mktemp 和 Linux GNU mktemp 对 -t 参数处理不同，改用不带 -t 的写法
OUTPUT_JSON="$(mktemp 2>/dev/null || mktemp /tmp/teleagent_db_check_XXXXXX.json)"
PY_SCRIPT="$(mktemp 2>/dev/null || mktemp /tmp/teleagent_db_check_XXXXXX.py)"

# Cleanup on exit (covers all exit paths)
cleanup() {
    [ -f "$PY_SCRIPT" ] && rm -f "$PY_SCRIPT" 2>/dev/null || true
}
trap cleanup EXIT

echo "[INFO] scheduler.db:    $SCHEDULER_DB"
echo "[INFO] im-service.db:   $IM_SERVICE_DB"
echo ""

# ============================================================
# Python Check Script (embedded)
# ============================================================
cat > "$PY_SCRIPT" << 'PYEOF'
# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import json

def check_file_header(db_path):
    """Check SQLite file header"""
    if not os.path.exists(db_path):
        return {"exists": False}
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        if len(header) < 16:
            return {"exists": True, "header_ok": False, "detail": "file too small ({} bytes)".format(len(header))}
        magic = header[:15]
        if magic == b"SQLite format 3":
            if header[15] == 0:
                return {"exists": True, "header_ok": True}
            else:
                return {"exists": True, "header_ok": False, "detail": "magic OK but terminator byte mismatch"}
        else:
            return {"exists": True, "header_ok": False, "detail": "not a SQLite file (header: {})".format(repr(header[:16]))}
    except Exception as e:
        return {"exists": True, "header_ok": False, "detail": str(e)}

def check_file_size(db_path):
    if not os.path.exists(db_path):
        return 0
    return os.path.getsize(db_path)

def check_integrity(db_path):
    """Run PRAGMA integrity_check"""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.execute("PRAGMA integrity_check;")
        result = cursor.fetchall()
        if len(result) == 1 and result[0][0] == "ok":
            return {"ok": True, "detail": "ok"}
        else:
            error_text = "; ".join([row[0] for row in result])
            return {"ok": False, "detail": error_text}
    except sqlite3.DatabaseError as e:
        return {"ok": False, "detail": "DatabaseError: {}".format(str(e))}
    except Exception as e:
        return {"ok": False, "detail": "{}: {}".format(type(e).__name__, str(e))}
    finally:
        if conn:
            conn.close()

def check_wal(wal_path, shm_path):
    """Check WAL and SHM file status"""
    result = {"wal_exists": False, "wal_size": 0, "wal_header_ok": True, "shm_exists": False, "detail": ""}
    if os.path.exists(wal_path):
        result["wal_exists"] = True
        result["wal_size"] = os.path.getsize(wal_path)
        if result["wal_size"] == 0:
            result["wal_header_ok"] = False
            result["detail"] += "WAL file is empty (0 bytes); "
        else:
            try:
                with open(wal_path, "rb") as f:
                    wal_header = f.read(4)
                if wal_header != b"\x37\x7f\x06\x82" and wal_header != b"\x37\x7f\x06\x83":
                    result["wal_header_ok"] = False
                    result["detail"] += "WAL header magic mismatch; "
            except Exception as e:
                result["wal_header_ok"] = False
                result["detail"] += "WAL read error: {}; ".format(str(e))
    if os.path.exists(shm_path):
        result["shm_exists"] = True
    return result

def determine_severity(header_result, integrity_result, wal_result):
    if not header_result.get("exists"):
        return "missing"
    if not header_result.get("header_ok"):
        return "severe"
    if integrity_result.get("ok"):
        if wal_result.get("wal_exists") and (not wal_result.get("wal_header_ok") or wal_result.get("wal_size") == 0):
            return "minor"
        return "healthy"
    detail = integrity_result.get("detail", "").lower()
    if "no such table" in detail or "database disk image is malformed" in detail:
        return "moderate"
    if "database is locked" in detail:
        return "locked"
    return "moderate"

def check_database(db_name, db_path):
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    header_result = check_file_header(db_path)
    file_size = check_file_size(db_path)

    if not header_result.get("exists"):
        return {
            "name": db_name, "path": db_path, "file_size": 0,
            "header_ok": False, "integrity_ok": False,
            "integrity_detail": "file not found",
            "wal": {"wal_exists": False, "wal_size": 0, "wal_header_ok": False, "shm_exists": False, "detail": ""},
            "severity": "missing", "overall": "[fail] file not found"
        }

    integrity_result = check_integrity(db_path)
    wal_result = check_wal(wal_path, shm_path)
    severity = determine_severity(header_result, integrity_result, wal_result)

    if severity == "healthy":
        overall = "[pass] database is healthy"
    elif severity == "minor":
        overall = "[warn] WAL file abnormal, main database OK"
    elif severity == "moderate":
        overall = "[fail] database corruption detected: " + integrity_result.get("detail", "")[:200]
    elif severity == "severe":
        overall = "[fail] file header corrupted: " + header_result.get("detail", "")
    elif severity == "locked":
        overall = "[warn] database is locked (may be in use): " + integrity_result.get("detail", "")[:200]
    elif severity == "missing":
        overall = "[fail] file not found"
    else:
        overall = "[fail] unknown issue"

    return {
        "name": db_name, "path": db_path, "file_size": file_size,
        "header_ok": header_result.get("header_ok", False),
        "integrity_ok": integrity_result.get("ok", False),
        "integrity_detail": integrity_result.get("detail", ""),
        "wal": wal_result, "severity": severity, "overall": overall
    }

def main():
    if len(sys.argv) < 5:
        print("ERROR: missing arguments")
        print("Usage: python db_check.py <scheduler.db> <im-service.db> <output_json> <mode>")
        sys.exit(1)

    scheduler_db = sys.argv[1]
    im_service_db = sys.argv[2]
    output_json = sys.argv[3]
    mode = sys.argv[4]

    results = {
        "scheduler": check_database("scheduler.db", scheduler_db),
        "im_service": check_database("im-service.db", im_service_db),
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("TeleAgent Database Health Check")
    print("=" * 60)

    for name, r in results.items():
        print()
        print("[{}]".format(r["name"]))
        print("  Path:          {}".format(r["path"]))
        print("  File size:     {} bytes".format(r["file_size"]))
        print("  Header:        {}".format("OK" if r["header_ok"] else "FAIL"))
        print("  Integrity:     {}".format("OK" if r["integrity_ok"] else "FAIL"))
        if r["integrity_detail"] and r["integrity_detail"] != "ok":
            print("  Detail:        {}".format(r["integrity_detail"][:200]))
        wal = r["wal"]
        if wal["wal_exists"]:
            print("  WAL:           exists ({} bytes, header: {})".format(
                wal["wal_size"], "OK" if wal["wal_header_ok"] else "ABNORMAL"))
        else:
            print("  WAL:           not present")
        if wal["shm_exists"]:
            print("  SHM:           present")
        print("  Severity:      {}".format(r["severity"]))
        print("  Status:        {}".format(r["overall"]))

    print()
    print("=" * 60)
    all_healthy = all(r["severity"] in ("healthy",) for r in results.values())
    any_missing = any(r["severity"] == "missing" for r in results.values())
    if all_healthy:
        print("[Summary] All databases are healthy. No repair needed.")
    elif any_missing:
        print("[Summary] Some database files are missing. Restart TeleAgent to recreate.")
    else:
        print("[Summary] Database issues detected. Repair is recommended.")
    print("=" * 60)

if __name__ == "__main__":
    main()
PYEOF

# Run Python check script
"$PYTHON" "$PY_SCRIPT" "$SCHEDULER_DB" "$IM_SERVICE_DB" "$OUTPUT_JSON" "check" || true

# Read results and determine exit code
if [ -f "$OUTPUT_JSON" ]; then
    echo ""
    echo "[OUTPUT] Detailed results saved to: $OUTPUT_JSON"

    # Check if repair is needed using Python
    NEED_REPAIR=$("$PYTHON" -c "
import json, sys
with open('$OUTPUT_JSON', 'r') as f:
    data = json.load(f)
need = any(v['severity'] not in ('healthy',) for v in data.values())
print('yes' if need else 'no')
" 2>/dev/null || echo "unknown")

    if [ "$NEED_REPAIR" = "yes" ]; then
        echo "[RESULT] Issues detected. Repair is recommended."
        exit 2
    elif [ "$NEED_REPAIR" = "no" ]; then
        echo "[RESULT] All databases are healthy."
        exit 0
    else
        echo "[RESULT] Could not determine status. Please review output above."
        exit 1
    fi
else
    echo "[ERROR] No output generated."
    # Clean up
    rm -f "$PY_SCRIPT" 2>/dev/null || true
    exit 1
fi

# Clean up Python script (keep JSON for agent to read)
# Handled by trap on EXIT
