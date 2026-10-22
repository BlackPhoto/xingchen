#!/bin/bash
# ============================================================
# TeleAgent 磁盘空间检测脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：扫描磁盘空间 → 检测各目录体积 → 三级分类 → 输出 JSON
# 用法：./check-disk-usage.sh
# 输出：JSON 格式评估结果，供 Agent 解析判断
# ============================================================

# 兼容处理：部分 Linux 发行版 python3 不在 PATH，回退到 python
if command -v python3 > /dev/null 2>&1; then
    PYTHON=python3
elif command -v python > /dev/null 2>&1; then
    PYTHON=python
else
    echo '{"disk_info":[],"running_processes":{},"has_admin":false,"categories":{"safe_to_clean":[],"caution_clean":[],"not_cleanable":[]},"safe_cleanable_total_mb":0,"caution_cleanable_total_mb":0,"locked_items_need_script":[],"cleanup_suggestion":"no_need","summary":"未找到 Python 3，无法运行检测脚本"}'
    exit 0
fi

$PYTHON << 'PYEOF'
# -*- coding: utf-8 -*-
import os, sys, json, glob, subprocess, shutil, re

# ============================================================
# 系统判定
# ============================================================

SYSTEM = os.uname().sysname if hasattr(os, 'uname') else sys.platform
IS_MAC = SYSTEM == "Darwin" or (isinstance(SYSTEM, str) and "darwin" in SYSTEM.lower())
IS_LINUX = not IS_MAC

HOME = os.path.expanduser("~")

# ============================================================
# 工具函数
# ============================================================

def get_dir_size_mb(path):
    """递归计算目录体积（MB）"""
    if not os.path.exists(path):
        return 0.0
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return round(total / (1024 * 1024), 1)

def get_glob_paths(pattern):
    """返回通配符匹配的路径列表"""
    return glob.glob(pattern)

def is_locked(path):
    """检测目录是否被进程占用（通过 lsof）"""
    if not os.path.exists(path) or not shutil.which('lsof'):
        return False
    try:
        result = subprocess.run(
            ['lsof', '+D', path],
            capture_output=True, text=True, timeout=10
        )
        return len(result.stdout.strip()) > 0
    except Exception:
        return False

def is_root():
    """检测是否有 root 权限"""
    return hasattr(os, 'geteuid') and os.geteuid() == 0

def check_process(name):
    """检测进程是否在运行"""
    # 优先使用 pgrep，不存在时回退到 ps aux | grep
    if shutil.which('pgrep'):
        try:
            result = subprocess.run(
                ['pgrep', '-i', name],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    else:
        try:
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False
            for line in result.stdout.strip().split('\n')[1:]:
                if name.lower() in line.lower():
                    return True
            return False
        except Exception:
            return False

def find_teleagent_data_dir():
    """定位 TeleAgent 数据目录（环境变量 → owner标记 → 探测 → 旧版回退）"""
    env_dir = os.environ.get('TELEAGENT_DATA_DIR')
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    base = os.path.join(HOME, '.local', 'share', 'TeleAgent')
    owner_file = os.path.join(base, 'current-owner.json')
    if os.path.isfile(owner_file):
        try:
            with open(owner_file, 'r', encoding='utf-8') as f:
                owner = json.load(f).get('ownerDir')
            if owner:
                d = os.path.join(base, 'users', owner)
                if os.path.isdir(d):
                    return d
        except Exception:
            pass
    users_root = os.path.join(base, 'users')
    if os.path.isdir(users_root):
        dirs = [os.path.join(users_root, x) for x in os.listdir(users_root)
                if os.path.isdir(os.path.join(users_root, x))]
        if dirs:
            return max(dirs, key=lambda p: os.path.getmtime(p))
    if os.path.isdir(base):
        return base
    return None

def to_gb(s):
    """将 df -h 的输出（如 512G、1.5T、856M）转换为 GB"""
    if not s:
        return 0.0
    s = s.upper().rstrip('B')
    # 去掉二进制前缀 I（如 Gi → G）
    s = s.replace('I', '')
    try:
        if s.endswith('T'):
            return round(float(s[:-1]) * 1024, 1)
        elif s.endswith('G'):
            return round(float(s[:-1]), 1)
        elif s.endswith('M'):
            return round(float(s[:-1]) / 1024, 2)
        elif s.endswith('K'):
            return round(float(s[:-1]) / (1024 * 1024), 2)
        else:
            return round(float(s) / (1024 * 1024), 2)
    except ValueError:
        return 0.0

# ============================================================
# 磁盘信息
# ============================================================

disk_info = []
try:
    # GNU df (Linux) 支持 --output，BSD df (macOS) 不支持
    if IS_MAC:
        df_cmd = ['df', '-h']
    else:
        df_cmd = ['df', '-h', '--output=source,size,used,avail,pcent']
    df_result = subprocess.run(
        df_cmd, capture_output=True, text=True, timeout=10
    )
    if df_result.returncode == 0:
        lines = df_result.stdout.strip().split('\n')[1:]
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                source = parts[0]
                if IS_MAC:
                    # BSD df -h 输出: Filesystem Size Used Avail Capacity
                    total = parts[1]
                    avail = parts[3]
                    pcent = parts[4].rstrip('%')
                else:
                    # GNU df --output: source size used avail pcent
                    total = parts[1]
                    avail = parts[3]
                    pcent = parts[4].rstrip('%')
                try:
                    usage_percent = float(pcent)
                except ValueError:
                    continue
                disk_info.append({
                    'drive': source,
                    'free_gb': to_gb(avail),
                    'total_gb': to_gb(total),
                    'usage_percent': usage_percent
                })
except Exception:
    pass

# ============================================================
# 进程状态
# ============================================================

running_processes = {
    'teleagent': check_process('teleagent') or check_process('teleclaw') or check_process('TeleAgent'),
    'chrome': check_process('chrome') or check_process('Google Chrome'),
    'edge': check_process('msedge') or check_process('Microsoft Edge'),
    'firefox': check_process('firefox'),
    'docker': check_process('docker'),
}

has_admin = is_root()

# ============================================================
# 定位 TeleAgent 目录
# ============================================================

teleagent_data_dir = find_teleagent_data_dir()

if IS_MAC:
    teleagent_cache_dir = os.path.join(HOME, 'Library', 'Caches', 'TeleAgent')
    teleagent_support_dir = os.path.join(HOME, 'Library', 'Application Support', 'TeleAgent')
    teleagent_log_dir = os.path.join(HOME, 'Library', 'Logs', 'TeleAgent')
else:
    teleagent_cache_dir = os.path.join(HOME, '.cache', 'TeleAgent')
    teleagent_config_dir = os.path.join(HOME, '.config', 'TeleAgent')
    teleagent_support_dir = None
    teleagent_log_dir = None

# ============================================================
# 收集扫描项
# ============================================================

safe_to_clean = []
caution_clean = []
locked_items = []

# --- 系统临时文件 ---
if IS_MAC:
    tmp_paths = ['/tmp']
    tmpdir = os.environ.get('TMPDIR')
    if tmpdir:
        tmp_paths.append(tmpdir.rstrip('/'))
else:
    tmp_paths = ['/tmp']

for tp in tmp_paths:
    if os.path.isdir(tp):
        sz = get_dir_size_mb(tp)
        locked = is_locked(tp)
        item = {
            'name': '系统临时文件',
            'path': tp,
            'size_mb': sz,
            'exists': True,
            'is_locked': locked,
            'needs_admin': False,
            'note': '部分文件可能被占用' if locked else '可直接清理'
        }
        safe_to_clean.append(item)
        if locked:
            locked_items.append({'name': item['name'], 'path': tp, 'size_mb': sz, 'blocking_process': 'unknown'})

# --- 回收站/废纸篓 ---
if IS_MAC:
    trash_path = os.path.join(HOME, '.Trash')
else:
    trash_path = os.path.join(HOME, '.local', 'share', 'Trash')

if os.path.isdir(trash_path):
    sz = get_dir_size_mb(trash_path)
    safe_to_clean.append({
        'name': '废纸篓' if IS_MAC else '回收站',
        'path': trash_path,
        'size_mb': sz,
        'exists': True,
        'is_locked': False,
        'needs_admin': False,
        'note': '可直接清理'
    })

# --- 系统日志 ---
if IS_MAC:
    sys_log_path = '/private/var/log'
else:
    sys_log_path = '/var/log'

if os.path.isdir(sys_log_path):
    sz = get_dir_size_mb(sys_log_path)
    caution_clean.append({
        'name': '系统日志',
        'path': sys_log_path,
        'size_mb': sz,
        'note': '建议保留最近7天，清理更旧的（需root权限）'
    })

# --- 用户缓存（非 TeleAgent） ---
if IS_MAC:
    user_cache_base = os.path.join(HOME, 'Library', 'Caches')
else:
    user_cache_base = os.path.join(HOME, '.cache')

if os.path.isdir(user_cache_base):
    # 扫描用户缓存中非 TeleAgent、非浏览器的子目录（浏览器缓存单独扫描）
    skip_prefixes = ('teleagent', 'google', 'chrome', 'mozilla', 'firefox',
                     'com.apple.safari', 'microsoft', 'msedge', 'edge',
                     'homebrew', 'pip', 'npm')
    try:
        for entry in os.listdir(user_cache_base):
            full_path = os.path.join(user_cache_base, entry)
            if os.path.isdir(full_path) and not entry.lower().startswith(skip_prefixes):
                sz = get_dir_size_mb(full_path)
                if sz > 50:
                    safe_to_clean.append({
                        'name': f'用户缓存({entry})',
                        'path': full_path,
                        'size_mb': sz,
                        'exists': True,
                        'is_locked': False,
                        'needs_admin': False,
                        'note': '可直接清理，应用会自动重建'
                    })
    except (OSError, PermissionError):
        pass

# --- 浏览器缓存 ---
if IS_MAC:
    browser_configs = [
        {'name': 'Chrome缓存', 'process': 'chrome', 'patterns': [
            os.path.join(HOME, 'Library/Caches/Google/Chrome/*/Cache'),
            os.path.join(HOME, 'Library/Application Support/Google/Chrome/*/Cache'),
        ]},
        {'name': 'Safari缓存', 'process': 'safari', 'patterns': [
            os.path.join(HOME, 'Library/Caches/com.apple.Safari'),
        ]},
        {'name': 'Firefox缓存', 'process': 'firefox', 'patterns': [
            os.path.join(HOME, 'Library/Caches/Firefox/*/cache2'),
            os.path.join(HOME, 'Library/Application Support/Firefox/Profiles/*/cache2'),
        ]},
    ]
else:
    browser_configs = [
        {'name': 'Chrome缓存', 'process': 'chrome', 'patterns': [
            os.path.join(HOME, '.cache/google-chrome/*/Cache'),
            os.path.join(HOME, '.config/google-chrome/*/Cache'),
        ]},
        {'name': 'Firefox缓存', 'process': 'firefox', 'patterns': [
            os.path.join(HOME, '.cache/mozilla/firefox/*/cache2'),
            os.path.join(HOME, '.mozilla/firefox/*/cache2'),
        ]},
    ]

for bc in browser_configs:
    found_paths = []
    seen_paths = set()
    for pat in bc['patterns']:
        for p in get_glob_paths(pat):
            norm = os.path.normpath(p).lower()
            if norm not in seen_paths:
                seen_paths.add(norm)
                found_paths.append(p)
    if found_paths:
        total_sz = 0.0
        for fp in found_paths:
            total_sz += get_dir_size_mb(fp)
        total_sz = round(total_sz, 1)
        is_running = running_processes.get(bc['process'], False)
        item = {
            'name': bc['name'],
            'path': '; '.join(found_paths),
            'size_mb': total_sz,
            'exists': True,
            'is_locked': is_running,
            'needs_admin': False,
            'note': f'需关闭 {bc["process"]} 后清理' if is_running else '可直接清理'
        }
        safe_to_clean.append(item)
        if is_running:
            locked_items.append({
                'name': bc['name'],
                'path': '; '.join(found_paths),
                'size_mb': total_sz,
                'blocking_process': bc['process']
            })

# --- Homebrew 缓存 (macOS) ---
if IS_MAC:
    brew_cache = os.path.join(HOME, 'Library', 'Caches', 'Homebrew')
    if os.path.isdir(brew_cache):
        sz = get_dir_size_mb(brew_cache)
        safe_to_clean.append({
            'name': 'Homebrew缓存',
            'path': brew_cache,
            'size_mb': sz,
            'exists': True,
            'is_locked': False,
            'needs_admin': False,
            'note': '可直接清理，下次安装时重新下载'
        })

# --- apt 缓存 (Linux) ---
if IS_LINUX and os.path.isdir('/var/cache/apt/archives'):
    sz = get_dir_size_mb('/var/cache/apt/archives')
    safe_to_clean.append({
        'name': 'apt缓存',
        'path': '/var/cache/apt/archives',
        'size_mb': sz,
        'exists': True,
        'is_locked': False,
        'needs_admin': True,
        'note': '可直接清理，下次安装时重新下载（需root权限）'
    })

# --- npm 缓存 ---
npm_cache = os.path.join(HOME, '.npm', '_cacache')
if os.path.isdir(npm_cache):
    sz = get_dir_size_mb(npm_cache)
    safe_to_clean.append({
        'name': 'npm缓存',
        'path': npm_cache,
        'size_mb': sz,
        'exists': True,
        'is_locked': False,
        'needs_admin': False,
        'note': '可直接清理，下次安装时重新下载'
    })

# --- pip 缓存 ---
if IS_MAC:
    pip_cache = os.path.join(HOME, 'Library', 'Caches', 'pip')
else:
    pip_cache = os.path.join(HOME, '.cache', 'pip')
if os.path.isdir(pip_cache):
    sz = get_dir_size_mb(pip_cache)
    safe_to_clean.append({
        'name': 'pip缓存',
        'path': pip_cache,
        'size_mb': sz,
        'exists': True,
        'is_locked': False,
        'needs_admin': False,
        'note': '可直接清理，下次安装时重新下载'
    })

# --- Docker 未使用资源 ---
if running_processes['docker']:
    try:
        docker_result = subprocess.run(
            ['docker', 'system', 'df'],
            capture_output=True, text=True, timeout=10
        )
        if docker_result.returncode == 0:
            lines = docker_result.stdout.strip().split('\n')[1:]
            docker_reclaimable = 0.0
            for line in lines:
                parts = line.split()
                if len(parts) >= 5:
                    # docker system df 输出: TYPE TOTAL ACTIVE SIZE RECLAIMABLE
                    # RECLAIMABLE 列格式如 "1.2GB (66%)"，取第5列
                    reclaimable_str = parts[4]
                    # 提取数值+单位部分（去掉括号百分比）
                    m = re.match(r'([\d.]+)\s*([A-Za-z]+)', reclaimable_str)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2).upper()
                        mb = {'GB': val * 1024, 'MB': val, 'KB': val / 1024, 'B': val / (1024*1024)}.get(unit, 0)
                        docker_reclaimable += mb
            if docker_reclaimable > 0:
                safe_to_clean.append({
                    'name': 'Docker未使用资源',
                    'path': 'docker system prune',
                    'size_mb': round(docker_reclaimable, 1),
                    'exists': True,
                    'is_locked': False,
                    'needs_admin': False,
                    'note': '可通过 docker system prune 清理未使用的镜像/容器/卷'
                })
    except Exception:
        pass

# --- Xcode DerivedData (macOS) ---
if IS_MAC:
    xcode_dd = os.path.join(HOME, 'Library', 'Developer', 'Xcode', 'DerivedData')
    if os.path.isdir(xcode_dd):
        sz = get_dir_size_mb(xcode_dd)
        safe_to_clean.append({
            'name': 'Xcode DerivedData',
            'path': xcode_dd,
            'size_mb': sz,
            'exists': True,
            'is_locked': False,
            'needs_admin': False,
            'note': '可直接清理，重新编译时自动重建'
        })

# --- Linux 旧内核 ---
if IS_LINUX:
    try:
        # 获取当前内核版本
        uname_result = subprocess.run(['uname', '-r'], capture_output=True, text=True, timeout=5)
        current_kernel = uname_result.stdout.strip()
        if current_kernel:
            boot_dir = '/boot'
            old_kernels = []
            if os.path.isdir(boot_dir):
                for f in os.listdir(boot_dir):
                    if f.startswith('vmlinuz-') or f.startswith('initrd.img-') or f.startswith('System.map-'):
                        ver = f.split('-')[1] if '-' in f else ''
                        if ver and ver not in current_kernel:
                            fp = os.path.join(boot_dir, f)
                            old_kernels.append(fp)
            if old_kernels:
                total_sz = 0.0
                for k in old_kernels:
                    try:
                        total_sz += os.path.getsize(k)
                    except OSError:
                        pass
                total_sz = round(total_sz / (1024*1024), 1)
                if total_sz > 0:
                    caution_clean.append({
                        'name': 'Linux旧内核',
                        'path': '; '.join(old_kernels[:4]) + ('...' if len(old_kernels) > 4 else ''),
                        'size_mb': total_sz,
                        'note': f'建议保留最近2个版本，清理更旧的（当前内核: {current_kernel}，需root权限）'
                    })
    except Exception:
        pass

# --- TeleAgent 相关清理项 ---
# TeleAgent 缓存可能在多个位置，统一收集候选目录
ta_cache_search_dirs = []
if IS_MAC:
    ta_cache_search_dirs = [
        teleagent_cache_dir,  # ~/Library/Caches/TeleAgent
        teleagent_support_dir,  # ~/Library/Application Support/TeleAgent
        teleagent_data_dir,  # ~/.local/share/TeleAgent
    ]
else:
    ta_cache_search_dirs = [
        teleagent_cache_dir,  # ~/.cache/TeleAgent
        os.path.join(HOME, '.config', 'TeleAgent'),
        teleagent_data_dir,  # ~/.local/share/TeleAgent
    ]
# 过滤 None 和不存在的目录，去重
ta_cache_search_dirs = list(dict.fromkeys(
    d for d in ta_cache_search_dirs if d and os.path.isdir(d)
))

# 统一的 TeleAgent 缓存检测函数
def check_ta_cache_subdir(search_dirs, subdir_name, item_name):
    """在多个候选目录中查找子目录（如 Cache/GPUCache/Code Cache），找到的全部加入扫描结果"""
    is_ta_running = running_processes['teleagent']
    for base_dir in search_dirs:
        cache_path = os.path.join(base_dir, subdir_name)
        if os.path.isdir(cache_path):
            sz = get_dir_size_mb(cache_path)
            item = {
                'name': item_name,
                'path': cache_path,
                'size_mb': sz,
                'exists': True,
                'is_locked': is_ta_running,
                'needs_admin': False,
                'note': '需关闭TeleAgent后清理' if is_ta_running else '可直接清理，重启后自动重建'
            }
            safe_to_clean.append(item)
            if is_ta_running:
                locked_items.append({
                    'name': item_name,
                    'path': cache_path,
                    'size_mb': sz,
                    'blocking_process': 'teleagent'
                })

# TeleAgent Cache
check_ta_cache_subdir(ta_cache_search_dirs, 'Cache', 'TeleAgent缓存')

# TeleAgent GPUCache
check_ta_cache_subdir(ta_cache_search_dirs, 'GPUCache', 'TeleAgent GPUCache')

# TeleAgent Code Cache
check_ta_cache_subdir(ta_cache_search_dirs, 'Code Cache', 'TeleAgent Code Cache')

# TeleAgent Crashpad（路径结构是 Crashpad/reports）
for base_dir in ta_cache_search_dirs:
    crash_path = os.path.join(base_dir, 'Crashpad', 'reports')
    if os.path.isdir(crash_path):
        sz = get_dir_size_mb(crash_path)
        safe_to_clean.append({
            'name': 'TeleAgent Crashpad报告',
            'path': crash_path,
            'size_mb': sz,
            'exists': True,
            'is_locked': False,
            'needs_admin': False,
            'note': '可直接清理'
        })

# TeleAgent 旧版本残留
# 在多个可能的父目录中搜索 TeleAgent* 目录
ta_search_bases = []
if IS_MAC:
    ta_search_bases = [
        os.path.join(HOME, 'Library', 'Application Support'),
        os.path.join(HOME, 'Library', 'Caches'),
        os.path.join(HOME, '.local', 'share'),
    ]
else:
    ta_search_bases = [
        os.path.join(HOME, '.config'),
        os.path.join(HOME, '.cache'),
        os.path.join(HOME, '.local', 'share'),
    ]

# 当前正在使用的 TeleAgent 目录（小写，用于排除）
ta_current_dirs = []
for d in [teleagent_cache_dir, teleagent_data_dir, teleagent_support_dir]:
    if d:
        ta_current_dirs.append(os.path.normpath(d).lower())

for search_base in ta_search_bases:
    if not os.path.isdir(search_base):
        continue
    try:
        for entry in os.listdir(search_base):
            if 'teleagent' in entry.lower():
                full_path = os.path.join(search_base, entry)
                norm_path = os.path.normpath(full_path).lower()
                if norm_path not in ta_current_dirs and os.path.isdir(full_path):
                    sz = get_dir_size_mb(full_path)
                    if sz > 1:
                        safe_to_clean.append({
                            'name': f'TeleAgent旧版本残留({entry})',
                            'path': full_path,
                            'size_mb': sz,
                            'exists': True,
                            'is_locked': False,
                            'needs_admin': False,
                            'note': '可直接清理，当前版本不再使用'
                        })
    except (OSError, PermissionError):
        pass

# --- TeleAgent 日志 (谨慎清理) ---
ta_log_dirs = []
# macOS: ~/Library/Logs/TeleAgent
if IS_MAC and teleagent_log_dir:
    ta_log_dirs.append(teleagent_log_dir)
# macOS: ~/Library/Application Support/TeleAgent/logs
if IS_MAC and teleagent_support_dir:
    ta_log_dirs.append(os.path.join(teleagent_support_dir, 'logs'))
# Linux: ~/.config/TeleAgent/logs（旧版 Electron 目录，兼容保留）
if IS_LINUX:
    ta_log_dirs.append(os.path.join(HOME, '.config', 'TeleAgent', 'logs'))
# 所有平台: 当前账号数据目录下的 log（单数，TeleAgent 2.6+ 账号日志目录）
if teleagent_data_dir:
    ta_log_dirs.append(os.path.join(teleagent_data_dir, 'log'))

# 去重并检测
seen_log_dirs = set()
for ta_log_dir in ta_log_dirs:
    norm = os.path.normpath(ta_log_dir).lower()
    if norm in seen_log_dirs:
        continue
    seen_log_dirs.add(norm)
    if os.path.isdir(ta_log_dir):
        sz = get_dir_size_mb(ta_log_dir)
        if sz > 0:
            caution_clean.append({
                'name': 'TeleAgent日志',
                'path': ta_log_dir,
                'size_mb': sz,
                'note': '建议保留最近7天，清理更旧的'
            })

# --- 下载目录大文件 (谨慎清理) ---
download_path = os.path.join(HOME, 'Downloads')
if os.path.isdir(download_path):
    large_files = []
    try:
        for f in os.listdir(download_path):
            fp = os.path.join(download_path, f)
            if os.path.isfile(fp) and not os.path.islink(fp):
                try:
                    if os.path.getsize(fp) > 100 * 1024 * 1024:
                        large_files.append(fp)
                except OSError:
                    pass
    except (OSError, PermissionError):
        pass
    if large_files:
        total_sz = 0.0
        for f in large_files:
            try:
                total_sz += os.path.getsize(f)
            except OSError:
                pass
        total_sz = round(total_sz / (1024*1024), 1)
        caution_clean.append({
            'name': '下载目录大文件(>100MB)',
            'path': download_path,
            'size_mb': total_sz,
            'note': f'需您确认哪些可删，共 {len(large_files)} 个文件'
        })

# --- 不可清理项 ---
not_cleanable = []

if teleagent_data_dir:
    db_paths = [
        os.path.join(teleagent_data_dir, 'scheduler', 'scheduler.db'),
        os.path.join(teleagent_data_dir, 'im-service', 'im-service.db'),
    ]
    db_found = []
    db_size = 0.0
    for db in db_paths:
        if os.path.isfile(db):
            try:
                db_size += os.path.getsize(db)
                db_found.append(db)
            except OSError:
                pass
    db_size = round(db_size / (1024*1024), 1)

    # 统计配置文件（标准路径在 ~/.config/TeleAgent/，不在数据目录）
    config_dir = os.path.join(HOME, '.config', 'TeleAgent')
    cfg_paths = [
        os.path.join(config_dir, 'TeleAgent.jsonc'),
    ]
    # 兼容旧版本：数据目录下可能存在配置文件
    cfg_paths.append(os.path.join(teleagent_data_dir, 'TeleAgent.jsonc'))
    cfg_found = [c for c in cfg_paths if os.path.isfile(c)]

    if db_found or cfg_found:
        not_cleanable.append({
            'name': 'TeleAgent数据库与配置',
            'paths': db_found + cfg_found,
            'size_mb': db_size,
            'note': '核心数据，不可删除'
        })

    mem_path = os.path.join(teleagent_data_dir, 'memory')
    if os.path.isdir(mem_path):
        mem_sz = get_dir_size_mb(mem_path)
        not_cleanable.append({
            'name': 'TeleAgent记忆目录',
            'paths': [mem_path],
            'size_mb': mem_sz,
            'note': '长期记忆数据，不可删除'
        })

# ============================================================
# 汇总
# ============================================================

safe_total = round(sum(s['size_mb'] for s in safe_to_clean), 1)
caution_total = round(sum(c['size_mb'] for c in caution_clean), 1)

if safe_total >= 100 and caution_total >= 100:
    cleanup_suggestion = 'all'
elif safe_total >= 100:
    cleanup_suggestion = 'safe_only'
else:
    cleanup_suggestion = 'no_need'

summary_parts = []
if safe_total >= 100:
    summary_parts.append(f'可安全清理约 {round(safe_total/1024, 1)} GB')
else:
    summary_parts.append(f'可安全清理空间有限（{safe_total} MB）')
if locked_items:
    locked_total = round(sum(l['size_mb'] for l in locked_items), 1)
    summary_parts.append(f'{len(locked_items)} 项被占用（约 {locked_total} MB）需关闭程序后清理')

result = {
    'disk_info': disk_info,
    'running_processes': running_processes,
    'has_admin': has_admin,
    'categories': {
        'safe_to_clean': safe_to_clean,
        'caution_clean': caution_clean,
        'not_cleanable': not_cleanable
    },
    'safe_cleanable_total_mb': safe_total,
    'caution_cleanable_total_mb': caution_total,
    'locked_items_need_script': locked_items,
    'cleanup_suggestion': cleanup_suggestion,
    'summary': '；'.join(summary_parts)
}

print(json.dumps(result, ensure_ascii=False, indent=2))
PYEOF
