#!/bin/bash
# ============================================================
# TeleAgent Database Repair Script (macOS / Linux)
# Three-tier repair:
#   Level 1 - WAL Recovery (delete .db-wal and .db-shm, keep main .db)
#   Level 2 - Data Recovery (export data to new database via Python sqlite3)
#   Level 3 - Delete and Rebuild (backup then remove, restart to recreate)
# Each level auto-verifies; failure escalates to next level.
#
# Usage:
#   ./db-repair.sh                       # repair both databases
#   ./db-repair.sh --targets scheduler   # repair only scheduler
#   ./db-repair.sh --targets im-service
#   ./db-repair.sh --force-level 2       # start from level 2
# ============================================================
set -e

# ============================================================
# Argument Parsing
# ============================================================
TARGETS="scheduler,im-service"
FORCE_LEVEL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --targets)
            TARGETS="$2"
            shift 2
            ;;
        --force-level)
            FORCE_LEVEL="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# ============================================================
# Path Resolution
# ============================================================
get_teleagent_data_dir() {
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
        local py_alt="$data_dir/runtimes/python/bin/python"
        if [ -x "$py_alt" ]; then
            echo "$py_alt"
            return 0
        fi
    fi
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
echo " TeleAgent Database Repair (macOS / Linux)"
echo "========================================"
echo ""

# Locate data directory
DATA_DIR="$(get_teleagent_data_dir)" || {
    echo "[ERROR] TeleAgent data directory not found."
    exit 1
}
echo "[INFO] Data directory: $DATA_DIR"

# Locate Python
PYTHON="$(get_teleagent_python)" || {
    echo "[ERROR] No Python found."
    exit 1
}
echo "[INFO] Python: $PYTHON"

# Write Python repair script to temp file
# 使用跨平台兼容的临时文件创建方式
# macOS BSD mktemp 和 Linux GNU mktemp 对 -t 参数处理不同，改用不带 -t 的写法
PY_SCRIPT="$(mktemp 2>/dev/null || mktemp /tmp/teleagent_db_repair_XXXXXX.py)"

cat > "$PY_SCRIPT" << 'PYEOF'
# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import json
import shutil
import time
import gc

def safe_remove(path, max_retries=3):
    for attempt in range(max_retries):
        try:
            os.remove(path)
            return True
        except PermissionError:
            gc.collect()
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:
                raise
    return False

def backup_files(db_path, suffix="bak"):
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backups = {}
    for ext in ["", "-wal", "-shm"]:
        src = db_path + ext
        if os.path.exists(src):
            dst = "{}.{}.{}".format(src, suffix, timestamp)
            shutil.copy2(src, dst)
            backups[ext if ext else "main"] = dst
    return backups

def check_integrity(db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.execute("PRAGMA integrity_check;")
        result = cursor.fetchall()
        return len(result) == 1 and result[0][0] == "ok", "; ".join(r[0] for r in result)
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

def get_table_schema(db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name;").fetchall()
        schemas = []
        for row in rows:
            schemas.append({"type": row["type"], "name": row["name"], "sql": row["sql"]})
        return True, schemas
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

def get_table_data(db_path, table_name):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM [{}]".format(table_name))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        data = []
        for row in rows:
            data.append(tuple(row[col] for col in columns))
        return True, columns, data
    except Exception as e:
        return False, str(e), None
    finally:
        if conn:
            conn.close()

def get_all_tables(db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

# ============================================================
# Level 1: WAL Recovery
# ============================================================
def level1_wal_recovery(db_path):
    result = {"level": 1, "action": "wal_recovery", "success": False, "detail": "", "backups": {}}
    result["backups"] = backup_files(db_path)
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    deleted = []
    if os.path.exists(wal_path):
        safe_remove(wal_path)
        deleted.append(os.path.basename(wal_path))
    if os.path.exists(shm_path):
        safe_remove(shm_path)
        deleted.append(os.path.basename(shm_path))
    if not deleted:
        ok, msg = check_integrity(db_path)
        if ok:
            result["success"] = True
            result["detail"] = "No WAL files found, main database already healthy"
        else:
            result["detail"] = "No WAL files found, main database still corrupt: " + msg[:200]
        return result
    ok, msg = check_integrity(db_path)
    if ok:
        result["success"] = True
        result["detail"] = "WAL recovery successful. Deleted: " + ", ".join(deleted)
    else:
        result["detail"] = "WAL recovery failed. Main database still corrupt: " + msg[:200]
    return result

# ============================================================
# Level 2: Data Recovery
# ============================================================
def level2_data_recovery(db_path):
    result = {"level": 2, "action": "data_recovery", "success": False, "detail": "", "backups": {}, "tables_recovered": [], "tables_failed": []}
    result["backups"] = backup_files(db_path)
    ok, schemas_or_err = get_table_schema(db_path)
    if not ok:
        result["detail"] = "Cannot read schema: " + str(schemas_or_err)[:200]
        return result
    schemas = schemas_or_err
    if not schemas:
        result["detail"] = "No tables found in database"
        return result
    new_db_path = db_path + ".recovered"
    if os.path.exists(new_db_path):
        safe_remove(new_db_path)
    new_conn = None
    try:
        new_conn = sqlite3.connect(new_db_path, timeout=5)
        new_conn.execute("PRAGMA journal_mode=WAL;")
        tables_created = 0
        indexes_created = 0
        for schema in schemas:
            if schema["type"] == "table":
                try:
                    new_conn.execute(schema["sql"])
                    tables_created += 1
                except Exception as e:
                    result["tables_failed"].append({"name": schema["name"], "error": str(e)[:100]})
        tables = get_all_tables(db_path)
        total_rows = 0
        for table_name in tables:
            ok, columns_or_err, data_or_none = get_table_data(db_path, table_name)
            if ok:
                columns = columns_or_err
                data = data_or_none
                if data:
                    placeholders = ", ".join(["?"] * len(columns))
                    col_names = ", ".join("[{}]".format(c) for c in columns)
                    try:
                        new_conn.executemany("INSERT INTO [{}] ({}) VALUES ({})".format(table_name, col_names, placeholders), data)
                        total_rows += len(data)
                        result["tables_recovered"].append({"name": table_name, "rows": len(data)})
                    except Exception as e:
                        result["tables_failed"].append({"name": table_name, "error": "insert failed: " + str(e)[:100]})
                else:
                    result["tables_recovered"].append({"name": table_name, "rows": 0})
            else:
                result["tables_failed"].append({"name": table_name, "error": "read failed: " + str(columns_or_err)[:100]})
        for schema in schemas:
            if schema["type"] == "index":
                try:
                    new_conn.execute(schema["sql"])
                    indexes_created += 1
                except Exception:
                    pass
        new_conn.commit()
    except Exception as e:
        result["detail"] = "Error during data recovery: " + str(e)[:200]
        return result
    finally:
        if new_conn:
            new_conn.close()
    ok, msg = check_integrity(new_db_path)
    if ok:
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        if os.path.exists(wal_path):
            safe_remove(wal_path)
        if os.path.exists(shm_path):
            safe_remove(shm_path)
        # Move recovered database to original location
        shutil.move(new_db_path, db_path)
        result["success"] = True
        result["detail"] = "Data recovery successful. Tables created: {}, Indexes created: {}, Rows recovered: {}".format(
            tables_created, indexes_created, total_rows)
    else:
        # Recovered database also corrupt, cleanup
        if os.path.exists(new_db_path):
            safe_remove(new_db_path)
        result["detail"] = "Recovered database also failed integrity check: " + msg[:200]
    return result

# ============================================================
# Level 3: Delete and Rebuild
# ============================================================
def level3_delete_rebuild(db_path):
    result = {"level": 3, "action": "delete_rebuild", "success": True, "detail": "", "backups": {}}
    result["backups"] = backup_files(db_path)
    deleted = []
    gc.collect()
    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            safe_remove(path)
            deleted.append(os.path.basename(path))
    result["detail"] = "Deleted: " + ", ".join(deleted) + ". TeleAgent will recreate on restart."
    return result

# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 5:
        print("ERROR: missing arguments")
        print("Usage: python db_repair.py <db_path> <db_name> <output_json> <force_level>")
        sys.exit(1)
    db_path = sys.argv[1]
    db_name = sys.argv[2]
    output_json = sys.argv[3]
    force_level = int(sys.argv[4])

    print("=" * 60)
    print("Repairing: {} ({})".format(db_name, db_path))
    print("=" * 60)

    ok, msg = check_integrity(db_path)
    if ok and force_level == 0:
        wal_path = db_path + "-wal"
        wal_abnormal = False
        if os.path.exists(wal_path) and os.path.getsize(wal_path) == 0:
            wal_abnormal = True
        if not wal_abnormal:
            print("[SKIP] Database is already healthy.")
            result = {"db_name": db_name, "skipped": True, "detail": "already healthy"}
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return

    start_level = force_level if force_level > 0 else 1
    repair_result = None

    for level in range(start_level, 4):
        print()
        print("--- Level {} ---".format(level))
        if level == 1:
            print("Action: WAL Recovery (delete .db-wal and .db-shm, keep main .db)")
            repair_result = level1_wal_recovery(db_path)
        elif level == 2:
            print("Action: Data Recovery (export data to new database)")
            repair_result = level2_data_recovery(db_path)
        elif level == 3:
            print("Action: Delete and Rebuild (remove all files, restart to recreate)")
            repair_result = level3_delete_rebuild(db_path)
        print("Result: {}".format("SUCCESS" if repair_result["success"] else "FAILED"))
        print("Detail: {}".format(repair_result["detail"][:200]))
        if repair_result["success"]:
            break
        if level < 3:
            print(">>> Escalating to Level {}...".format(level + 1))

    final_ok = False
    final_msg = ""
    if repair_result and repair_result.get("success"):
        if repair_result["level"] == 3:
            if not os.path.exists(db_path):
                final_ok = True
                final_msg = "Files deleted successfully. Restart TeleAgent to recreate."
            else:
                final_ok = False
                final_msg = "File still exists after deletion attempt."
        else:
            ok, msg = check_integrity(db_path)
            final_ok = ok
            final_msg = msg

    output = {
        "db_name": db_name, "db_path": db_path, "skipped": False,
        "repair_level": repair_result["level"] if repair_result else 0,
        "repair_action": repair_result["action"] if repair_result else "",
        "repair_success": repair_result["success"] if repair_result else False,
        "repair_detail": repair_result["detail"] if repair_result else "",
        "backups": repair_result.get("backups", {}) if repair_result else {},
        "tables_recovered": repair_result.get("tables_recovered", []) if repair_result else [],
        "tables_failed": repair_result.get("tables_failed", []) if repair_result else [],
        "final_integrity_ok": final_ok,
        "final_integrity_detail": final_msg,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    if final_ok:
        print("[RESULT] Repair successful! Please restart TeleAgent.")
    else:
        print("[RESULT] Repair failed. Manual intervention may be needed.")
    print("=" * 60)

if __name__ == "__main__":
    main()
PYEOF

# ============================================================
# Repair Loop
# ============================================================

ALL_SUCCESS=true
declare -a SUMMARY_ENTRIES=()

# Cleanup temp files on exit
cleanup() {
    rm -f "$PY_SCRIPT" 2>/dev/null || true
    for entry in "${SUMMARY_ENTRIES[@]}"; do
        json_path="${entry#*|}"
        rm -f "$json_path" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Convert TARGETS to array
IFS=',' read -ra TARGET_ARRAY <<< "$TARGETS"

# DB path mapping
getDbPath() {
    case "$1" in
        scheduler)
            echo "$DATA_DIR/scheduler/scheduler.db"
            ;;
        im-service)
            echo "$DATA_DIR/im-service/im-service.db"
            ;;
        *)
            echo ""
            ;;
    esac
}

getDbName() {
    case "$1" in
        scheduler)  echo "scheduler.db" ;;
        im-service) echo "im-service.db" ;;
        *)          echo "unknown" ;;
    esac
}

for target in "${TARGET_ARRAY[@]}"; do
    target="$(echo "$target" | xargs)"  # trim whitespace
    target_lower="$(echo "$target" | tr '[:upper:]' '[:lower:]')"

    db_name="$(getDbName "$target_lower")"
    db_path="$(getDbPath "$target_lower")"

    if [ -z "$db_path" ]; then
        echo "[WARN] Unknown target: $target, skipping."
        SUMMARY_ENTRIES+=("$db_name|")
        ALL_SUCCESS=false
        continue
    fi

    output_json="$(mktemp 2>/dev/null || mktemp /tmp/teleagent_db_repair_${target_lower}_XXXXXX.json)"

    echo ""
    echo ">>> Repairing $db_name ..."

    if [ ! -f "$db_path" ]; then
        echo "[WARN] File not found: $db_path"
        # Write a result JSON so summary can report it
        "$PYTHON" -c "
import json, sys
result = {
    'db_name': sys.argv[1],
    'skipped': False,
    'repair_success': False,
    'repair_level': 0,
    'repair_detail': 'Database file not found: ' + sys.argv[2],
    'final_integrity_ok': False,
    'final_integrity_detail': 'File not found',
}
with open(sys.argv[3], 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
" "$db_name" "$db_path" "$output_json" 2>/dev/null || true
        SUMMARY_ENTRIES+=("$db_name|$output_json")
        ALL_SUCCESS=false
        continue
    fi

    "$PYTHON" "$PY_SCRIPT" "$db_path" "$db_name" "$output_json" "$FORCE_LEVEL" || true

    # Check result — read JSON via Python using sys.argv (safe against spaces in paths)
    if [ -f "$output_json" ]; then
        repair_status=$("$PYTHON" -c "
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
# Skipped = already healthy, not a failure
if data.get('skipped'):
    print('skipped')
elif data.get('repair_success') and data.get('final_integrity_ok'):
    print('success')
else:
    print('fail')
" "$output_json" 2>/dev/null || echo "fail")

        if [ "$repair_status" = "fail" ]; then
            ALL_SUCCESS=false
        fi
    else
        ALL_SUCCESS=false
    fi

    SUMMARY_ENTRIES+=("$db_name|$output_json")
done

# Summarize
echo ""
echo "========================================"
echo " Repair Summary"
echo "========================================"

for entry in "${SUMMARY_ENTRIES[@]}"; do
    db_name="${entry%%|*}"
    json_path="${entry#*|}"

    if [ -n "$json_path" ] && [ -f "$json_path" ]; then
        "$PYTHON" -c "
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)

if data.get('skipped'):
    print('  {}: [SKIPPED] Already healthy'.format(sys.argv[2]))
else:
    status = 'OK' if data.get('repair_success') and data.get('final_integrity_ok') else 'FAIL'
    print('  {}: [{}] (Level {})'.format(sys.argv[2], status, data.get('repair_level', 0)))
    detail = data.get('repair_detail', '')
    if detail:
        print('    Detail: {}'.format(detail[:200]))
    recovered = data.get('tables_recovered', [])
    if recovered:
        parts = ['{}({} rows)'.format(t['name'], t['rows']) for t in recovered]
        print('    Recovered: {}'.format(', '.join(parts)))
    failed = data.get('tables_failed', [])
    if failed:
        names = [t['name'] for t in failed]
        print('    Failed tables: {}'.format(', '.join(names)))
" "$json_path" "$db_name" 2>/dev/null || echo "  $db_name: [UNKNOWN]"
    else
        echo "  $db_name: [NO RESULT]"
    fi
done

echo ""
if [ "$ALL_SUCCESS" = true ]; then
    echo "[DONE] All repairs completed successfully."
    echo "  Please restart TeleAgent for changes to take effect."
    exit 0
else
    echo "[DONE] Some repairs failed. Review details above."
    echo "  Please restart TeleAgent and check if issues persist."
    exit 2
fi
