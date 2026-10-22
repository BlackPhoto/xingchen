#!/usr/bin/env bash
# ============================================================
# TeleAgent 正在运行的软件与显存占用检测脚本 (macOS / Linux)
# ============================================================
# 功能：枚举进程 → 统计内存/CPU → 检测 GPU 显存 → 输出 JSON
# 用法：chmod +x check-running-software.sh && ./check-running-software.sh
# 输出：JSON 格式检测结果，供 Agent 解析展示
# ============================================================

set -euo pipefail

OS_NAME="$(uname -s)"

# ============================================================
# 排除的系统核心进程
# ============================================================
EXCLUDED_LINUX="systemd|kthreadd|rcu_gp|migration|watchdog|ksoftirqd|kworker|kswapd|jbd2|ext4|scsi|ata|edac|devfreq|netns|crypto|charger|mptcp|ipv6"
EXCLUDED_MACOS="kernel_task|loginwindow|WindowServer|launchd|syslogd|configd|distnoted|securityd|CFUser|rpc|mds|mdworker|findmydeviced|coreauthd|ceserver|Dock|routined|passd|accountsd|nsurlsessiond|chronod"
EXCLUDED_COMMON="^$"

# ============================================================
# 运行中的软件
# ============================================================

if [ "$OS_NAME" = "Darwin" ]; then
    # macOS: ps 列出进程，带路径
    # -c 获取短命令名，-o 自定义格式
    RAW_PS=$(ps -eo pid=,comm=,rss=,pcpu= 2>/dev/null || echo "")
    EXCLUDE_PATTERN="$EXCLUDED_MACOS"
else
    # Linux
    RAW_PS=$(ps -eo pid=,comm=,rss=,pcpu= --no-headers 2>/dev/null || echo "")
    EXCLUDE_PATTERN="$EXCLUDED_LINUX"
fi

# 用 Python 处理分组排序和 JSON 输出
python3 - "$RAW_PS" "$EXCLUDE_PATTERN" "$OS_NAME" << 'PYTHON_SCRIPT'
import sys
import json
import os
import subprocess
import re

raw_ps = sys.argv[1]
exclude_pattern = sys.argv[2]
os_name = sys.argv[3]

# 解析 ps 输出
processes = []
for line in raw_ps.strip().split('\n'):
    if not line.strip():
        continue
    parts = line.split(None, 4)
    if len(parts) < 4:
        continue
    try:
        pid = int(parts[0].strip())
        name = parts[1].strip()
        rss_kb = float(parts[2].strip())
        cpu = float(parts[3].strip())
        mem_mb = round(rss_kb / 1024, 1)
        processes.append({
            'pid': pid,
            'name': name,
            'memory_mb': mem_mb,
            'cpu_percent': cpu,
            'path': ''
        })
    except (ValueError, IndexError):
        continue

# 获取进程路径（macOS: lsof, Linux: /proc）
for proc in processes:
    try:
        if os_name == "Darwin":
            # macOS: 用 ps -o command= 获取完整命令行（含路径）
            result = subprocess.run(
                ['ps', '-p', str(proc['pid']), '-o', 'command='],
                capture_output=True, text=True, timeout=2
            )
            if result.stdout.strip():
                proc['path'] = result.stdout.strip()
        else:
            # Linux: 读 /proc/pid/exe 或 /proc/pid/cmdline
            exe_path = f"/proc/{proc['pid']}/exe"
            if os.path.exists(exe_path):
                proc['path'] = os.readlink(exe_path)
            else:
                cmdline_path = f"/proc/{proc['pid']}/cmdline"
                if os.path.exists(cmdline_path):
                    with open(cmdline_path, 'r', errors='replace') as f:
                        cmdline = f.read().split('\0')[0]
                        if cmdline:
                            proc['path'] = cmdline
    except Exception:
        pass

# 过滤排除项
exclude_re = re.compile(exclude_pattern, re.IGNORECASE) if exclude_pattern else None
filtered = []
for proc in processes:
    if exclude_re and exclude_re.search(proc['name']):
        continue
    # 排除内核线程（名字被方括号包裹，如 [kworker/0:1]）
    if proc['name'].startswith('[') and proc['name'].endswith(']'):
        continue
    filtered.append(proc)

# 按进程名分组
grouped = {}
for proc in filtered:
    name = proc['name']
    if name not in grouped:
        grouped[name] = []
    grouped[name].append(proc)

# 合并同进程名
running_software = []
total_memory = 0.0
for name, instances in grouped.items():
    main_proc = instances[0]
    instance_count = len(instances)
    mem_total = round(sum(p['memory_mb'] for p in instances), 1)
    cpu_total = round(sum(p['cpu_percent'] for p in instances), 1)
    total_memory += mem_total

    running_software.append({
        'name': name,
        'pid': main_proc['pid'],
        'instance_count': instance_count,
        'memory_mb': mem_total,
        'cpu_seconds': cpu_total,
        'path': main_proc['path']
    })

# 按内存排序
running_software.sort(key=lambda x: x['memory_mb'], reverse=True)
total_memory = round(total_memory, 1)

# ============================================================
# 系统内存
# ============================================================
system_memory = {
    'total_gb': 0,
    'available_gb': 0,
    'used_gb': 0,
    'usage_percent': 0
}

try:
    if os_name == "Darwin":
        # macOS: sysctl + vm_stat
        mem_total_bytes = int(subprocess.check_output(
            ['sysctl', '-n', 'hw.memsize'], timeout=5
        ).decode().strip())
        page_size = int(subprocess.check_output(
            ['sysctl', '-n', 'hw.pagesize'], timeout=5
        ).decode().strip())
        vm_stat = subprocess.check_output(['vm_stat'], timeout=5).decode()
        free_pages = 0
        for line in vm_stat.split('\n'):
            if 'Pages free' in line or 'Pages inactive' in line:
                val = re.search(r'(\d[\d,]*)', line)
                if val:
                    free_pages += int(val.group(1).replace(',', ''))
        total_gb = round(mem_total_bytes / (1024**3), 1)
        available_gb = round(free_pages * page_size / (1024**3), 1)
        used_gb = round(total_gb - available_gb, 1)
        usage_pct = round((total_gb - available_gb) / total_gb * 100, 1) if total_gb > 0 else 0
        system_memory = {
            'total_gb': total_gb,
            'available_gb': available_gb,
            'used_gb': used_gb,
            'usage_percent': usage_pct
        }
    else:
        # Linux: /proc/meminfo
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    val_kb = int(parts[1])
                    meminfo[key] = val_kb
        total_kb = meminfo.get('MemTotal', 0)
        available_kb = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
        total_gb = round(total_kb / 1024 / 1024, 1)
        available_gb = round(available_kb / 1024 / 1024, 1)
        used_gb = round((total_kb - available_kb) / 1024 / 1024, 1)
        usage_pct = round((total_kb - available_kb) / total_kb * 100, 1) if total_kb > 0 else 0
        system_memory = {
            'total_gb': total_gb,
            'available_gb': available_gb,
            'used_gb': used_gb,
            'usage_percent': usage_pct
        }
except Exception:
    pass

# ============================================================
# GPU 显存检测
# ============================================================
gpu_info = []
gpu_processes = []
gpu_notes = []

# --- NVIDIA (nvidia-smi) ---
nvidia_smi_available = False
try:
    result = subprocess.run(['nvidia-smi'], capture_output=True, timeout=5)
    if result.returncode == 0:
        nvidia_smi_available = True
except Exception:
    pass

if nvidia_smi_available:
    try:
        # GPU 设备信息
        gpu_output = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=name,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            timeout=10
        ).decode().strip()
        for line in gpu_output.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                gpu_name = parts[0]
                used_mb = round(float(parts[1]), 1)
                total_mb = round(float(parts[2]), 1)
                usage_pct = round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0
                gpu_info.append({
                    'name': gpu_name,
                    'vendor': 'nvidia',
                    'used_mb': used_mb,
                    'total_mb': total_mb,
                    'usage_percent': usage_pct
                })

        # GPU 逐进程显存
        proc_output = subprocess.check_output(
            ['nvidia-smi', '--query-compute-apps=pid,name,used_memory',
             '--format=csv,noheader,nounits'],
            timeout=10
        ).decode().strip()
        if proc_output and 'No running compute processes' not in proc_output:
            for line in proc_output.split('\n'):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    gpu_processes.append({
                        'name': parts[1],
                        'pid': int(parts[0]),
                        'gpu_memory_mb': round(float(parts[2]), 1)
                    })
    except Exception as e:
        gpu_notes.append(f"nvidia-smi 执行失败：{str(e)}")
else:
    # nvidia-smi 不可用
    # 检查是否有 NVIDIA GPU
    has_nvidia = False
    try:
        if os_name == "Darwin":
            # macOS 通常无 NVIDIA GPU（2018+ Mac）
            pass
        else:
            # Linux: lspci
            result = subprocess.run(
                ['lspci'], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and 'NVIDIA' in result.stdout:
                has_nvidia = True
                gpu_notes.append("检测到 NVIDIA GPU，但 nvidia-smi 不可用，请确认 NVIDIA 驱动已正确安装")
    except Exception:
        pass

    if not has_nvidia:
        # 检查 AMD (Linux: rocm-smi)
        try:
            if os_name != "Darwin":
                rocm_result = subprocess.run(
                    ['rocm-smi'], capture_output=True, timeout=5
                )
                if rocm_result.returncode == 0:
                    # 尝试获取 GPU 信息
                    rocm_output = subprocess.check_output(
                        ['rocm-smi', '--showmeminfo', 'vram', '--csv'],
                        timeout=10
                    ).decode().strip()
                    # 简单解析
                    gpu_notes.append("检测到 AMD GPU（rocm-smi 可用），但逐进程显存查询支持有限")
        except Exception:
            pass

        # 检查 Intel 集显
        try:
            if os_name != "Darwin":
                lspci_result = subprocess.run(
                    ['lspci'], capture_output=True, text=True, timeout=5
                )
                if lspci_result.returncode == 0:
                    if 'Intel' in lspci_result.stdout and 'VGA' in lspci_result.stdout:
                        gpu_notes.append("检测到 Intel 集显，暂不支持逐进程显存查询")
        except Exception:
            pass

        if not gpu_notes:
            gpu_notes.append("未检测到 GPU 设备或 GPU 检测工具不可用")

    # 通过 lspci 获取 GPU 设备名（Linux）
    if os_name != "Darwin" and not gpu_info:
        try:
            lspci_result = subprocess.run(
                ['lspci'], capture_output=True, text=True, timeout=5
            )
            if lspci_result.returncode == 0:
                for line in lspci_result.stdout.split('\n'):
                    if 'VGA compatible controller' in line or '3D controller' in line:
                        gpu_name = line.split(':')[-1].strip() if ':' in line else line.strip()
                        vendor = 'unknown'
                        if 'NVIDIA' in gpu_name:
                            vendor = 'nvidia'
                        elif 'AMD' in gpu_name or 'Radeon' in gpu_name:
                            vendor = 'amd'
                        elif 'Intel' in gpu_name:
                            vendor = 'intel'
                        gpu_info.append({
                            'name': gpu_name,
                            'vendor': vendor,
                            'used_mb': 0,
                            'total_mb': 0,
                            'usage_percent': 0
                        })
        except Exception:
            pass

# macOS: 尝试通过 system_profiler 获取 GPU 信息
if os_name == "Darwin" and not gpu_info:
    try:
        sp_output = subprocess.check_output(
            ['system_profiler', 'SPDisplaysDataType'],
            timeout=10
        ).decode()
        # 解析 GPU 名称
        for line in sp_output.split('\n'):
            if 'Chipset Model' in line or 'VRAM' in line:
                if 'Chipset Model' in line:
                    gpu_name = line.split(':')[-1].strip()
                    gpu_info.append({
                        'name': gpu_name,
                        'vendor': 'apple',
                        'used_mb': 0,
                        'total_mb': 0,
                        'usage_percent': 0
                    })
                    gpu_notes.append(f"macOS GPU（{gpu_name}）暂不支持逐进程显存查询")
    except Exception:
        pass

# ============================================================
# 输出 JSON
# ============================================================
result = {
    'running_software': running_software,
    'total_memory_mb': total_memory,
    'system_memory': system_memory,
    'gpu': gpu_info,
    'gpu_processes': gpu_processes,
    'gpu_detection_notes': gpu_notes
}

print(json.dumps(result, ensure_ascii=False, indent=2))
PYTHON_SCRIPT
