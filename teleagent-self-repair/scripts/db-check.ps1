#requires -version 5.1
<#
.SYNOPSIS
    TeleAgent 数据库健康检查脚本（Windows）
.DESCRIPTION
    检查 scheduler.db 和 im-service.db 的完整性，输出结构化诊断结果。
    使用 TeleAgent 自带的 Python 运行时执行 SQLite 操作，无需系统安装 sqlite3 CLI。
.NOTES
    检查项：文件存在性、文件头校验、PRAGMA integrity_check、WAL 文件状态
#>

$ErrorActionPreference = "Stop"

# ============================================================
# 路径定位
# ============================================================

function Get-TeleAgentDataDir {
    # 优先使用环境变量
    if ($env:TELEAGENT_DATA_DIR -and (Test-Path $env:TELEAGENT_DATA_DIR)) {
        return $env:TELEAGENT_DATA_DIR
    }
    # 兜底：读 owner 标记拼 users\<owner>
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
    # 查找 TeleAgent 自带的 Python
    # 内置 runtime 位于“数据根\runtimes”（而非账号数据目录 users\<账号>\ 下）
    $dataDir = Get-TeleAgentDataDir
    if ($dataDir) {
        # 数据根 = 账号数据目录上一级（…\TeleAgent\users\<账号> → …\TeleAgent）
        $dataRoot = Split-Path -Parent (Split-Path -Parent $dataDir)
        $candidates = @(
            (Join-Path $dataRoot "runtimes\python\python.exe"),
            (Join-Path $dataDir "runtimes\python\python.exe")   # 旧结构兜底
        )
        foreach ($p in $candidates) {
            if ($p -and (Test-Path $p)) { return $p }
        }
    }
    # 回退到系统 Python
    $sysPy = Get-Command python -ErrorAction SilentlyContinue
    if ($sysPy) {
        return $sysPy.Source
    }
    return $null
}

# ============================================================
# Python 检测脚本（内嵌）
# ============================================================

$pyCheckScript = @'
# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import json

def check_file_header(db_path):
    """检查 SQLite 文件头"""
    if not os.path.exists(db_path):
        return {"exists": False}
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        if len(header) < 16:
            return {"exists": True, "header_ok": False, "detail": "file too small ({} bytes)".format(len(header))}
        magic = header[:15]
        if magic == b"SQLite format 3":
            # 检查第16字节是否为 \x00
            if header[15] == 0:
                return {"exists": True, "header_ok": True}
            else:
                return {"exists": True, "header_ok": False, "detail": "magic OK but terminator byte mismatch"}
        else:
            return {"exists": True, "header_ok": False, "detail": "not a SQLite file (header: {})".format(repr(header[:16]))}
    except Exception as e:
        return {"exists": True, "header_ok": False, "detail": str(e)}

def check_file_size(db_path):
    """检查文件大小"""
    if not os.path.exists(db_path):
        return 0
    return os.path.getsize(db_path)

def check_integrity(db_path):
    """执行 PRAGMA integrity_check"""
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
    """检查 WAL 和 SHM 文件状态"""
    result = {"wal_exists": False, "wal_size": 0, "wal_header_ok": True, "shm_exists": False, "detail": ""}
    # WAL 检查
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
                # WAL 文件头魔数: 0x377f0682 或 0x377f0683 (大端)
                if wal_header != b"\x37\x7f\x06\x82" and wal_header != b"\x37\x7f\x06\x83":
                    result["wal_header_ok"] = False
                    result["detail"] += "WAL header magic mismatch; "
            except Exception as e:
                result["wal_header_ok"] = False
                result["detail"] += "WAL read error: {}; ".format(str(e))
    # SHM 检查
    if os.path.exists(shm_path):
        result["shm_exists"] = True
    return result

def determine_severity(header_result, integrity_result, wal_result):
    """确定损坏级别"""
    if not header_result.get("exists"):
        return "missing"
    if not header_result.get("header_ok"):
        return "severe"
    if integrity_result.get("ok"):
        # 主库正常，检查 WAL
        if wal_result.get("wal_exists") and (not wal_result.get("wal_header_ok") or wal_result.get("wal_size") == 0):
            return "minor"  # WAL 异常，主库正常
        return "healthy"
    # 主库 integrity_check 失败
    detail = integrity_result.get("detail", "").lower()
    if "no such table" in detail or "database disk image is malformed" in detail:
        return "moderate"
    if "database is locked" in detail:
        return "locked"
    return "moderate"

def check_database(db_name, db_path):
    """检查单个数据库"""
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"

    header_result = check_file_header(db_path)
    file_size = check_file_size(db_path)

    if not header_result.get("exists"):
        return {
            "name": db_name,
            "path": db_path,
            "file_size": 0,
            "header_ok": False,
            "integrity_ok": False,
            "integrity_detail": "file not found",
            "wal": {"wal_exists": False, "wal_size": 0, "wal_header_ok": False, "shm_exists": False, "detail": ""},
            "severity": "missing",
            "overall": "[fail] file not found"
        }

    integrity_result = check_integrity(db_path)
    wal_result = check_wal(wal_path, shm_path)
    severity = determine_severity(header_result, integrity_result, wal_result)

    # 构造整体状态
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
        "name": db_name,
        "path": db_path,
        "file_size": file_size,
        "header_ok": header_result.get("header_ok", False),
        "integrity_ok": integrity_result.get("ok", False),
        "integrity_detail": integrity_result.get("detail", ""),
        "wal": wal_result,
        "severity": severity,
        "overall": overall
    }

def main():
    # 从命令行参数获取路径
    if len(sys.argv) < 5:
        print("ERROR: missing arguments")
        print("Usage: python db_check.py <scheduler.db> <im-service.db> <output_json> <mode>")
        sys.exit(1)

    scheduler_db = sys.argv[1]
    im_service_db = sys.argv[2]
    output_json = sys.argv[3]
    mode = sys.argv[4]  # "check" or "verify"

    results = {
        "scheduler": check_database("scheduler.db", scheduler_db),
        "im_service": check_database("im-service.db", im_service_db),
    }

    # 输出到 JSON 文件
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 控制台输出
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
    # 汇总
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
'@

# ============================================================
# 主流程
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " TeleAgent Database Health Check (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 定位数据目录
$dataDir = Get-TeleAgentDataDir
if (-not $dataDir) {
    Write-Host "[ERROR] TeleAgent data directory not found." -ForegroundColor Red
    Write-Host "  Standard path: $env:USERPROFILE\.local\share\TeleAgent" -ForegroundColor Yellow
    Write-Host "  Or set TELEAGENT_DATA_DIR environment variable." -ForegroundColor Yellow
    exit 1
}
Write-Host "[INFO] Data directory: $dataDir" -ForegroundColor Green

# 定位 Python
$python = Get-TeleAgentPython
if (-not $python) {
    Write-Host "[ERROR] No Python found. Neither TeleAgent Python runtime nor system Python available." -ForegroundColor Red
    exit 1
}
Write-Host "[INFO] Python: $python" -ForegroundColor Green

# 定义数据库路径
$schedulerDb = Join-Path $dataDir "scheduler\scheduler.db"
$imServiceDb = Join-Path $dataDir "im-service\im-service.db"
$outputJson = Join-Path $env:TEMP "teleagent-db-check-result.json"

Write-Host "[INFO] scheduler.db:    $schedulerDb" -ForegroundColor Gray
Write-Host "[INFO] im-service.db:   $imServiceDb" -ForegroundColor Gray
Write-Host ""

# 写入 Python 脚本到临时文件
$pyScriptPath = Join-Path $env:TEMP "teleagent_db_check.py"
$pyCheckScript | Out-File -FilePath $pyScriptPath -Encoding utf8 -Force

# 运行 Python 检测脚本
try {
    & $python $pyScriptPath $schedulerDb $imServiceDb $outputJson "check" 2>&1 | ForEach-Object {
        $line = $_.ToString()
        if ($line -match "\[pass\]") {
            Write-Host $line -ForegroundColor Green
        } elseif ($line -match "\[warn\]") {
            Write-Host $line -ForegroundColor Yellow
        } elseif ($line -match "\[fail\]") {
            Write-Host $line -ForegroundColor Red
        } elseif ($line -match "\[Summary\]") {
            Write-Host $line -ForegroundColor Cyan
        } else {
            Write-Host $line
        }
    }

    # 读取 JSON 结果
    if (Test-Path $outputJson) {
        $result = Get-Content $outputJson -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ""
        Write-Host "[OUTPUT] Detailed results saved to: $outputJson" -ForegroundColor Gray

        # 检查是否需要修复
        $needRepair = $false
        foreach ($prop in $result.PSObject.Properties.Name) {
            $db = $result.$prop
            if ($db.severity -notin @("healthy")) {
                $needRepair = $true
                break
            }
        }
        if ($needRepair) {
            Write-Host "[RESULT] Issues detected. Repair is recommended." -ForegroundColor Yellow
            exit 2
        } else {
            Write-Host "[RESULT] All databases are healthy." -ForegroundColor Green
            exit 0
        }
    } else {
        Write-Host "[ERROR] No output generated." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERROR] Script execution failed: $_" -ForegroundColor Red
    exit 1
} finally {
    # 清理临时 Python 脚本
    if (Test-Path $pyScriptPath) { Remove-Item $pyScriptPath -Force -ErrorAction SilentlyContinue }
}
