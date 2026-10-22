#requires -version 5.1
<#
.SYNOPSIS
    TeleAgent 数据库修复脚本（Windows）
.DESCRIPTION
    三级修复流程：
      Level 1 - WAL 恢复（删除 .db-wal 和 .db-shm，保留主库）
      Level 2 - 数据恢复（用 Python sqlite3 导出数据到新库）
      Level 3 - 删除重建（备份后删除，重启自动重建）
    每级修复后自动验证，失败则进入下一级。
.NOTES
    参数：
      -Targets "scheduler","im-service"  指定修复目标（默认两个都修）
      -ForceLevel 1|2|3                  强制从指定级别开始（跳过前面级别）
#>

param(
    [string[]]$Targets = @("scheduler", "im-service"),
    [int]$ForceLevel = 0
)

$ErrorActionPreference = "Stop"

# ============================================================
# 路径定位
# ============================================================

function Get-TeleAgentDataDir {
    if ($env:TELEAGENT_DATA_DIR -and (Test-Path $env:TELEAGENT_DATA_DIR)) {
        return $env:TELEAGENT_DATA_DIR
    }
    # 兜底：读 owner 标记拼 users\<owner>\
    $ownerFile = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "current-owner.json"
    if (Test-Path $ownerFile) {
        try {
            $owner = (Get-Content $ownerFile -Raw | ConvertFrom-Json).ownerDir
            if ($owner) {
                $d = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users") $owner
                if (Test-Path $d) { return $d }
            }
        } catch {}
    }
    # 再兜底：探测活跃子目录
    $usersRoot = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users"
    if (Test-Path $usersRoot) {
        $latest = Get-ChildItem $usersRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) { return $latest.FullName }
    }
    # 最后回退根目录（旧版）
    $standardPath = Join-Path $env:USERPROFILE ".local\share\TeleAgent"
    if (Test-Path $standardPath) {
        return $standardPath
    }
    return $null
}

function Get-TeleAgentPython {
    $dataDir = Get-TeleAgentDataDir
    if ($dataDir) {
        # 内置 runtime 位于“实际数据根\runtimes”（而非账号目录 users\账号\ 下）
        $dataRoot = Split-Path -Parent (Split-Path -Parent $dataDir)
        $candidates = @(
            (Join-Path $dataRoot "runtimes\python\python.exe"),
            (Join-Path $dataDir "runtimes\python\python.exe")   # 旧结构兜底
        )
        foreach ($p in $candidates) {
            if ($p -and (Test-Path $p)) { return $p }
        }
    }
    $sysPy = Get-Command python -ErrorAction SilentlyContinue
    if ($sysPy) {
        return $sysPy.Source
    }
    return $null
}


# ============================================================
# Python 修复脚本（内嵌）
# ============================================================

$pyRepairScript = @'
# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import json
import shutil
import time
import gc

def safe_remove(path, max_retries=3):
    """安全删除文件，带重试逻辑（Windows 文件锁问题）"""
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
    """备份 .db, .db-wal, .db-shm 文件"""
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
    """检查完整性"""
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
    """获取所有表结构和索引"""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name;").fetchall()
        schemas = []
        for row in rows:
            schemas.append({
                "type": row["type"],
                "name": row["name"],
                "sql": row["sql"]
            })
        return True, schemas
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

def get_table_data(db_path, table_name):
    """获取表数据"""
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
    """获取所有表名"""
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

def get_all_indexes(db_path):
    """获取所有索引（非自动索引）"""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name;").fetchall()
        return rows
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

# ============================================================
# Level 1: WAL Recovery
# ============================================================
def level1_wal_recovery(db_path):
    """删除 WAL 和 SHM 文件，保留主库"""
    result = {"level": 1, "action": "wal_recovery", "success": False, "detail": "", "backups": {}}

    # 备份
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
        result["detail"] = "No WAL/SHM files found to delete"
        # Check if main db is already OK
        ok, msg = check_integrity(db_path)
        if ok:
            result["success"] = True
            result["detail"] = "No WAL files found, main database already healthy"
        else:
            result["detail"] = "No WAL files found, main database still corrupt: " + msg[:200]
        return result

    # Verify
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
    """恢复数据到新数据库"""
    result = {"level": 2, "action": "data_recovery", "success": False, "detail": "", "backups": {}, "tables_recovered": [], "tables_failed": []}

    # 备份
    result["backups"] = backup_files(db_path)

    # 尝试读取表结构
    ok, schemas_or_err = get_table_schema(db_path)
    if not ok:
        result["detail"] = "Cannot read schema: " + str(schemas_or_err)[:200]
        return result

    schemas = schemas_or_err
    if not schemas:
        result["detail"] = "No tables found in database"
        return result

    # 创建新数据库
    new_db_path = db_path + ".recovered"
    if os.path.exists(new_db_path):
        safe_remove(new_db_path)

    try:
        new_conn = sqlite3.connect(new_db_path, timeout=5)
        new_conn.execute("PRAGMA journal_mode=WAL;")
    except Exception as e:
        result["detail"] = "Cannot create new database: " + str(e)[:200]
        return result

    try:
        # 重建表结构
        tables_created = 0
        indexes_created = 0
        for schema in schemas:
            if schema["type"] == "table":
                try:
                    new_conn.execute(schema["sql"])
                    tables_created += 1
                except Exception as e:
                    result["tables_failed"].append({"name": schema["name"], "error": str(e)[:100]})

        # 恢复数据
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

        # 重建索引
        for schema in schemas:
            if schema["type"] == "index":
                try:
                    new_conn.execute(schema["sql"])
                    indexes_created += 1
                except Exception:
                    pass

        new_conn.commit()
    except Exception as e:
        result["detail"] = "Data recovery error: " + str(e)[:200]
        return result
    finally:
        new_conn.close()

    # 验证新数据库
    ok, msg = check_integrity(new_db_path)
    if ok:
        # 替换原文件：先删旧的 wal/shm，再用新库替换
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        if os.path.exists(wal_path):
            safe_remove(wal_path)
        if os.path.exists(shm_path):
            safe_remove(shm_path)
        # 移动新库到原位置
        shutil.move(new_db_path, db_path)
        result["success"] = True
        result["detail"] = "Data recovery successful. Tables created: {}, Indexes created: {}, Rows recovered: {}".format(
            tables_created, indexes_created, total_rows)
    else:
        # 新库也损坏，清理
        if os.path.exists(new_db_path):
            safe_remove(new_db_path)
        result["detail"] = "Recovered database also failed integrity check: " + msg[:200]

    return result

# ============================================================
# Level 3: Delete and Rebuild
# ============================================================
def level3_delete_rebuild(db_path):
    """删除数据库文件，重启后自动重建"""
    result = {"level": 3, "action": "delete_rebuild", "success": True, "detail": "", "backups": {}}

    # 备份
    result["backups"] = backup_files(db_path)

    # 删除所有相关文件
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
    force_level = int(sys.argv[4])  # 0=auto, 1/2/3=force from level

    print("=" * 60)
    print("Repairing: {} ({})".format(db_name, db_path))
    print("=" * 60)

    # 初始完整性检查
    ok, msg = check_integrity(db_path)
    if ok and force_level == 0:
        # 检查 WAL 状态
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

    # 执行修复
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

    # 最终验证（Level 3 跳过验证，因为文件已删除）
    final_ok = False
    final_msg = ""
    if repair_result and repair_result.get("success"):
        if repair_result["level"] == 3:
            # 文件已删除，验证文件不存在
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

    # 输出结果
    output = {
        "db_name": db_name,
        "db_path": db_path,
        "skipped": False,
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
'@

# ============================================================
# 主流程
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " TeleAgent Database Repair (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 定位数据目录
$dataDir = Get-TeleAgentDataDir
if (-not $dataDir) {
    Write-Host "[ERROR] TeleAgent data directory not found." -ForegroundColor Red
    exit 1
}
Write-Host "[INFO] Data directory: $dataDir" -ForegroundColor Green

# 定位 Python
$python = Get-TeleAgentPython
if (-not $python) {
    Write-Host "[ERROR] No Python found." -ForegroundColor Red
    exit 1
}
Write-Host "[INFO] Python: $python" -ForegroundColor Green

# 构建目标数据库映射
$dbMap = @{
    "scheduler"  = @{ name = "scheduler.db";  path = (Join-Path $dataDir "scheduler\scheduler.db") }
    "im-service" = @{ name = "im-service.db"; path = (Join-Path $dataDir "im-service\im-service.db") }
}

# 写入 Python 脚本到临时文件
$pyScriptPath = Join-Path $env:TEMP "teleagent_db_repair.py"
$pyRepairScript | Out-File -FilePath $pyScriptPath -Encoding utf8 -Force

# 逐个修复目标数据库
$allSuccess = $true
$repairResults = @()

foreach ($target in $Targets) {
    $target = $target.ToLower().Trim()
    if (-not $dbMap.ContainsKey($target)) {
        Write-Host "[WARN] Unknown target: $target, skipping." -ForegroundColor Yellow
        continue
    }

    $dbName = $dbMap[$target].name
    $dbPath = $dbMap[$target].path
    $outputJson = Join-Path $env:TEMP "teleagent-db-repair-$target-result.json"

    Write-Host ""
    Write-Host ">>> Repairing $dbName ..." -ForegroundColor Cyan

    if (-not (Test-Path $dbPath)) {
        Write-Host "[WARN] File not found: $dbPath" -ForegroundColor Yellow
        $repairResults += @{ db_name = $dbName; repair_success = $false; final_integrity_ok = $false; repair_level = 0; repair_detail = "file not found" }
        $allSuccess = $false
        continue
    }

    try {
        & $python $pyScriptPath $dbPath $dbName $outputJson $ForceLevel 2>&1 | ForEach-Object {
            $line = $_.ToString()
            if ($line -match "\[RESULT\]") {
                Write-Host $line -ForegroundColor Green
            } elseif ($line -match "SUCCESS") {
                Write-Host $line -ForegroundColor Green
            } elseif ($line -match "FAILED|ERROR") {
                Write-Host $line -ForegroundColor Red
            } elseif ($line -match ">>> Escalating|--- Level") {
                Write-Host $line -ForegroundColor Yellow
            } else {
                Write-Host $line
            }
        }

        # 读取结果
        if (Test-Path $outputJson) {
            $result = Get-Content $outputJson -Raw -Encoding UTF8 | ConvertFrom-Json
            $repairResults += $result
            # skipped 表示数据库已健康，不算失败
            if ($result.skipped -eq $true) {
                # already healthy, not a failure
            } elseif (-not $result.repair_success -or -not $result.final_integrity_ok) {
                $allSuccess = $false
            }
        }
    } catch {
        Write-Host "[ERROR] Repair failed for $dbName : $_" -ForegroundColor Red
        $repairResults += @{ db_name = $dbName; repair_success = $false; final_integrity_ok = $false; repair_level = 0; repair_detail = $_.ToString() }
        $allSuccess = $false
    }
}

# 清理临时脚本
if (Test-Path $pyScriptPath) { Remove-Item $pyScriptPath -Force -ErrorAction SilentlyContinue }

# 汇总输出
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Repair Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($r in $repairResults) {
    if ($r.skipped -eq $true) {
        Write-Host "  $($r.db_name): [SKIPPED] Already healthy" -ForegroundColor Gray
        continue
    }
    $status = if ($r.final_integrity_ok) { "OK" } elseif ($r.repair_success) { "OK" } else { "FAIL" }
    $color = if ($status -eq "OK") { "Green" } else { "Red" }
    Write-Host "  $($r.db_name): [$status] (Level $($r.repair_level))" -ForegroundColor $color
    if ($r.repair_detail) {
        Write-Host "    Detail: $($r.repair_detail)" -ForegroundColor Gray
    }
    if ($r.PSObject.Properties.Name -contains "tables_recovered" -and $r.tables_recovered) {
        $recovered = ($r.tables_recovered | ForEach-Object { "$($_.name)($($_.rows) rows)" }) -join ", "
        Write-Host "    Recovered: $recovered" -ForegroundColor Gray
    }
    if ($r.PSObject.Properties.Name -contains "tables_failed" -and $r.tables_failed) {
        $failed = ($r.tables_failed | ForEach-Object { $_.name }) -join ", "
        Write-Host "    Failed tables: $failed" -ForegroundColor Yellow
    }
}

Write-Host ""
if ($allSuccess) {
    Write-Host "[DONE] All repairs completed successfully." -ForegroundColor Green
    Write-Host "  Please restart TeleAgent for changes to take effect." -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "[DONE] Some repairs failed. Review details above." -ForegroundColor Yellow
    Write-Host "  Please restart TeleAgent and check if issues persist." -ForegroundColor Cyan
    exit 2
}
