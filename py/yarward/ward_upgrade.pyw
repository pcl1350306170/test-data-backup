# ward_upgrade.pyw - 病房前端一键升级工具

import os
import json
import logging
import threading
import zipfile
import tarfile
import tempfile
import shutil
import glob as glob_module
from pathlib import Path
from datetime import datetime
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==============================
# 第三方库导入
# ==============================
try:
    import paramiko
except ImportError:
    paramiko = None

try:
    import pymysql
except ImportError:
    pymysql = None

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "ward_upgrade"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True, parents=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8')]
)
logger = logging.getLogger()

# 服务器路径
WEB_REMOTE_PATH = "/home/data/web"
WEB_BACKUP_ITEMS = ["assets", "static", "login.html", "index.html", "home.html"]
BACKUP_BASE_PATH = "/home/data/web/bak"  # 统一备份目录

# 默认密码
DEFAULT_SSH_PASSWORDS = ["Huawei@123", "rd2021+", "yh123456"]
DEFAULT_MYSQL_PASSWORDS = ["Yahua@3585668", "Yahua3585668yh"]

# ==============================
# 配置函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return {
        "servers": {},
        "last_server": "",
        "ssh_user": "root",
        "upgrade_dir": "",
        "mysql_host": "",
        "mysql_port": 3306,
        "mysql_db": "YHDB",
        "mysql_password": ""
    }


def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


# ==============================
# SSH/SFTP 工具函数
# ==============================
def get_ssh_client(host, username="root", password="", timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=username, password=password, timeout=timeout)
    return client


def clear_remote_path(sftp, remote_path):
    """递归删除远程文件或目录"""
    try:
        stat = sftp.stat(remote_path)
        import stat as stat_module
        if stat_module.S_ISDIR(stat.st_mode):
            files = sftp.listdir(remote_path)
            for f in files:
                clear_remote_path(sftp, f"{remote_path.rstrip('/')}/{f}")
            sftp.rmdir(remote_path)
        else:
            sftp.remove(remote_path)
    except IOError:
        pass  # 文件不存在


def ensure_remote_dir(sftp, remote_path, log):
    """确保远程目录存在"""
    try:
        sftp.stat(remote_path)
        return True
    except FileNotFoundError:
        parent = '/'.join(remote_path.split('/')[:-1])
        if parent and parent != '/':
            ensure_remote_dir(sftp, parent, log)
        try:
            sftp.mkdir(remote_path)
            log(f"创建远程目录: {remote_path}")
        except Exception:
            pass
        return True


def upload_dir(sftp, local_dir, remote_dir, log):
    """递归上传本地目录到远程"""
    ensure_remote_dir(sftp, remote_dir, log)
    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir.rstrip('/')}/{item}"
        if os.path.isfile(local_path):
            sftp.put(local_path, remote_path)
        elif os.path.isdir(local_path):
            upload_dir(sftp, local_path, remote_path, log)


def extract_archive(archive_path, dest_dir, log):
    """智能解压压缩包，自动尝试多种格式（先尝试 tar 系列，再尝试 zip）"""
    errors = []

    # 先通过文件头魔字节判断真实格式
    with open(archive_path, 'rb') as f:
        header = f.read(4)

    # gzip 魔字节: 1f 8b
    if header[:2] == b'\x1f\x8b':
        try:
            log("文件头识别为 gzip，尝试 tar.gz 解压...")
            with tarfile.open(archive_path, 'r:gz') as tf:
                tf.extractall(dest_dir)
            return
        except Exception as e:
            errors.append(f"tar.gz: {e}")
    # zip 魔字节: 50 4b (PK)
    elif header[:2] == b'PK':
        try:
            log("文件头识别为 zip，解压中...")
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_dir)
            return
        except Exception as e:
            errors.append(f"zip: {e}")
    # bzip2 魔字节: 42 5a (BZ)
    elif header[:2] == b'BZ':
        try:
            log("文件头识别为 bzip2，尝试 tar.bz2 解压...")
            with tarfile.open(archive_path, 'r:bz2') as tf:
                tf.extractall(dest_dir)
            return
        except Exception as e:
            errors.append(f"tar.bz2: {e}")
    else:
        # 魔字节未匹配，依次尝试所有格式
        log(f"文件头未识别({header[:2].hex()})，依次尝试各格式...")

    # 魔字节未命中或失败时，依次尝试剩余格式
    for fmt, open_fn, label in [
        ('r:gz',  lambda p: tarfile.open(p, 'r:gz'),  'tar.gz'),
        ('r:',    lambda p: tarfile.open(p, 'r:'),     'tar'),
        ('r:bz2', lambda p: tarfile.open(p, 'r:bz2'),  'tar.bz2'),
        ('zip',   None,                                 'zip'),
    ]:
        try:
            if label == 'zip':
                log(f"尝试 zip 格式解压...")
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(dest_dir)
            else:
                log(f"尝试 {label} 格式解压...")
                with open_fn(archive_path) as tf:
                    tf.extractall(dest_dir)
            return
        except Exception as e:
            if f"{label}:" not in str(errors):
                errors.append(f"{label}: {e}")

    raise ValueError(f"无法解压文件 {os.path.basename(archive_path)}，尝试过的格式: {'; '.join(errors)}")


# ==============================
# Web 升级逻辑
# ==============================
def do_web_upgrade(host, username, password, web_package_path, log):
    """Web 前端升级：备份 → 清理 → 上传"""
    log(f"正在以用户 {username} 连接服务器...")
    with get_ssh_client(host, username=username, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 1. 检查 web 目录是否存在，不存在则创建
        try:
            sftp.stat(WEB_REMOTE_PATH)
        except IOError:
            log(f"服务器不存在 {WEB_REMOTE_PATH} 目录，自动创建")
            ensure_remote_dir(sftp, WEB_REMOTE_PATH, log)

        # 2. 备份到统一目录 /home/data/web/bak
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{BACKUP_BASE_PATH}/web_{timestamp}"
        ensure_remote_dir(sftp, backup_dir, log)
        log(f"备份目录: {backup_dir}")

        for item in WEB_BACKUP_ITEMS:
            remote_item = f"{WEB_REMOTE_PATH}/{item}"
            try:
                sftp.stat(remote_item)
                log(f"备份: {item}")
                stdin, stdout, stderr = ssh.exec_command(f"cp -r {remote_item} {backup_dir}/")
                stdout.channel.recv_exit_status()
            except IOError:
                log(f"跳过（不存在）: {item}")

        # 3. 删除原文件
        log("清理服务器文件...")
        for item in WEB_BACKUP_ITEMS:
            clear_remote_path(sftp, f"{WEB_REMOTE_PATH}/{item}")

        # 4. 解压并上传
        log("解压升级包...")
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_archive(web_package_path, tmpdir, log)

            # 查找解压后的 web 内容目录（持续剥掉单目录包装层）
            web_content_dir = Path(tmpdir)
            while True:
                children = list(web_content_dir.iterdir())
                if len(children) == 1 and children[0].is_dir():
                    log(f"剥掉包装目录: {children[0].name}")
                    web_content_dir = children[0]
                else:
                    break
            log(f"实际内容目录: {web_content_dir.name}")

            log(f"上传文件到 {WEB_REMOTE_PATH}...")
            upload_dir(sftp, str(web_content_dir), WEB_REMOTE_PATH, log)

        sftp.close()
    log("✅ Web 升级完成！")


# ==============================
# 看板升级逻辑
# ==============================
KANBAN_REMOTE_PATH = "/home/data/web/ntv"


def do_kanban_upgrade(host, username, password, kanban_package_path, log):
    """看板升级：备份 → 清空 → 解压上传"""
    log(f"正在以用户 {username} 连接服务器...")
    with get_ssh_client(host, username=username, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 1. 检查 ntv 目录是否存在，不存在则创建
        ntv_exists = True
        try:
            sftp.stat(KANBAN_REMOTE_PATH)
        except IOError:
            ntv_exists = False
            log(f"服务器不存在 {KANBAN_REMOTE_PATH} 目录，自动创建")
            ensure_remote_dir(sftp, KANBAN_REMOTE_PATH, log)

        # 2. 备份到统一目录 /home/data/web/bak
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{BACKUP_BASE_PATH}/ntv_{timestamp}"
        ensure_remote_dir(sftp, backup_dir, log)
        log(f"看板备份目录: {backup_dir}")

        if ntv_exists:
            stdin, stdout, stderr = ssh.exec_command(f"cp -r {KANBAN_REMOTE_PATH}/. {backup_dir}/")
            stdout.channel.recv_exit_status()
            log(f"备份完成: {KANBAN_REMOTE_PATH}")
        else:
            log("跳过备份（ntv 目录刚创建，无内容）")

        # 3. 清空 /home/data/web/ntv 目录内容（保留 ntv 目录本身）
        log(f"清空目录: {KANBAN_REMOTE_PATH}")
        for item in sftp.listdir(KANBAN_REMOTE_PATH):
            clear_remote_path(sftp, f"{KANBAN_REMOTE_PATH}/{item}")
            log(f"  删除: {item}")

        # 4. 解压并上传 ntv 目录内容
        log("解压看板升级包...")
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_archive(kanban_package_path, tmpdir, log)

            # 查找解压后的 ntv 目录
            extracted = list(Path(tmpdir).iterdir())
            ntv_content_dir = None
            if len(extracted) == 1 and extracted[0].is_dir() and extracted[0].name == 'ntv':
                ntv_content_dir = extracted[0]
            else:
                # 递归查找 ntv 目录
                for item in Path(tmpdir).rglob('ntv'):
                    if item.is_dir():
                        ntv_content_dir = item
                        break
                if ntv_content_dir is None:
                    # 如果找不到 ntv 目录，使用解压根目录
                    ntv_content_dir = Path(tmpdir)
                    log("⚠️ 未找到 ntv 子目录，使用解压根目录")

            log(f"上传看板文件到 {KANBAN_REMOTE_PATH}...")
            upload_dir(sftp, str(ntv_content_dir), KANBAN_REMOTE_PATH, log)

        sftp.close()
    log("✅ 看板升级完成！")


# ==============================
# 床头/床旁 设备升级逻辑
# ==============================
def do_device_upgrade(host, username, password, device_name, remote_path, source_type, source_path, log):
    """
    床头/床旁升级通用函数
    device_name: 设备名称（bedhead / bedside）
    remote_path: 服务器目标目录
    source_type: 'dir' 本地目录直接覆盖上传 或 'package' 压缩包备份→清空→解压上传
    source_path: 本地目录路径 或 压缩包路径
    """
    log(f"正在以用户 {username} 连接服务器...")
    with get_ssh_client(host, username=username, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 检查目标目录是否存在，不存在则创建
        try:
            sftp.stat(remote_path)
        except IOError:
            log(f"服务器不存在 {remote_path} 目录，自动创建")
            ensure_remote_dir(sftp, remote_path, log)

        if source_type == 'dir':
            # 本地目录模式：不备份、不清空，直接覆盖上传
            log(f"本地目录模式，直接覆盖上传到 {remote_path}...")
            upload_dir(sftp, source_path, remote_path, log)
        else:
            # 压缩包模式：备份 → 清空 → 解压上传
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = f"{BACKUP_BASE_PATH}/{device_name}_{timestamp}"
            ensure_remote_dir(sftp, backup_dir, log)
            log(f"备份目录: {backup_dir}")

            items = sftp.listdir(remote_path)
            if items:
                stdin, stdout, stderr = ssh.exec_command(f"cp -r {remote_path}/. {backup_dir}/")
                stdout.channel.recv_exit_status()
                log(f"备份完成: {remote_path}")
            else:
                log("目标目录为空，跳过备份")

            # 清空目标目录
            log(f"清空目录: {remote_path}")
            for item in sftp.listdir(remote_path):
                clear_remote_path(sftp, f"{remote_path}/{item}")
                log(f"  删除: {item}")

            # 解压并上传
            log("解压升级包...")
            with tempfile.TemporaryDirectory() as tmpdir:
                extract_archive(source_path, tmpdir, log)

                # 查找解压后的设备目录（持续剥掉单目录包装层）
                content_dir = Path(tmpdir)
                while True:
                    children = list(content_dir.iterdir())
                    if len(children) == 1 and children[0].is_dir():
                        log(f"剥掉包装目录: {children[0].name}")
                        content_dir = children[0]
                    else:
                        break

                log(f"上传文件到 {remote_path}...")
                upload_dir(sftp, str(content_dir), remote_path, log)

        sftp.close()
    log(f"✅ {device_name} 升级完成！")


# ==============================
# 菜单脚本升级逻辑
# ==============================
def do_menu_upgrade(host, mysql_config, upgrade_dir, log):
    """菜单脚本升级：查找菜单数据/权限相关 SQL 文件并执行"""
    sql_files = []

    # 查找菜单相关的 SQL 文件（以"菜单"开头，排除床头卡脚本）
    for f in Path(upgrade_dir).iterdir():
        if f.is_file() and f.suffix.lower() == '.sql':
            name = f.stem  # 不含扩展名
            if name.startswith('菜单') and '床头卡' not in name:
                sql_files.append(f)

    if not sql_files:
        log("⚠️ 升级目录中未找到菜单相关 SQL 文件（菜单*.sql）")
        return

    # 按文件名排序，确保执行顺序稳定
    sql_files.sort(key=lambda x: x.name)

    log(f"找到 {len(sql_files)} 个菜单 SQL 文件:")
    for f in sql_files:
        log(f"  - {f.name}")

    # 连接 MySQL
    mysql_host = mysql_config['host']
    mysql_port = mysql_config.get('port', 3306)
    mysql_db = mysql_config.get('db', 'YHDB')
    mysql_pwd = mysql_config['password']

    log(f"连接 MySQL: {mysql_host}:{mysql_port}/{mysql_db}...")
    conn = pymysql.connect(
        host=mysql_host,
        port=int(mysql_port),
        user='root',
        password=mysql_pwd,
        database=mysql_db,
        charset='utf8mb4',
        autocommit=False
    )

    try:
        cursor = conn.cursor()
        for sql_file in sql_files:
            log(f"执行 SQL: {sql_file.name}")
            content = sql_file.read_text(encoding='utf-8')

            # 按分号分割语句
            statements = []
            current = []
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith('--') or stripped.startswith('#'):
                    continue
                current.append(line)
                if stripped.endswith(';'):
                    stmt = '\n'.join(current).strip()
                    if stmt and stmt != ';':
                        statements.append(stmt)
                    current = []

            # 处理最后一条没有分号的语句
            if current:
                stmt = '\n'.join(current).strip()
                if stmt and stmt != ';':
                    statements.append(stmt)

            success_count = 0
            error_count = 0
            for stmt in statements:
                try:
                    cursor.execute(stmt)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"SQL 语句执行失败: {e}\n语句: {stmt[:100]}...")

            log(f"  ✅ 成功: {success_count} 条, ⚠️ 失败: {error_count} 条")

        conn.commit()
        cursor.close()
        log("✅ 菜单脚本升级完成！")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"菜单脚本升级失败: {e}")
    finally:
        conn.close()


# ==============================
# 床头卡脚本升级逻辑
# ==============================
def _parse_sql_statements(content):
    """解析文本中的 SQL 语句，返回语句列表"""
    statements = []
    current = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('--') or stripped.startswith('#'):
            continue
        current.append(line)
        if stripped.endswith(';'):
            stmt = '\n'.join(current).strip()
            if stmt and stmt != ';':
                statements.append(stmt)
            current = []
    # 处理最后一条没有分号的语句
    if current:
        stmt = '\n'.join(current).strip()
        if stmt and stmt != ';':
            statements.append(stmt)
    return statements


def _is_sql_content(content):
    """判断文本内容是否包含 SQL 语句"""
    upper = content.upper()
    keywords = ['INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'ALTER ', 'DROP ', 'REPLACE ']
    return any(kw in upper for kw in keywords)


def do_bedcard_sql_upgrade(mysql_config, upgrade_dir, log):
    """床头卡脚本升级：扫描 .txt/.sql 文件，识别并执行 SQL 语句"""
    sql_files = []

    # 查找升级目录下的 .txt 和 .sql 文件
    for f in Path(upgrade_dir).iterdir():
        if f.is_file() and f.suffix.lower() in ('.sql', '.txt'):
            # 读取内容判断是否包含 SQL
            try:
                content = f.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    content = f.read_text(encoding='gbk')
                except Exception:
                    continue
            if _is_sql_content(content):
                sql_files.append((f, content))

    if not sql_files:
        log("⚠️ 升级目录中未找到包含 SQL 语句的 .txt/.sql 文件")
        return

    log(f"找到 {len(sql_files)} 个床头卡 SQL 文件:")
    for f, _ in sql_files:
        log(f"  - {f.name}")

    # 连接 MySQL
    mysql_host = mysql_config['host']
    mysql_port = mysql_config.get('port', 3306)
    mysql_db = mysql_config.get('db', 'YHDB')
    mysql_pwd = mysql_config['password']

    log(f"连接 MySQL: {mysql_host}:{mysql_port}/{mysql_db}...")
    conn = pymysql.connect(
        host=mysql_host,
        port=int(mysql_port),
        user='root',
        password=mysql_pwd,
        database=mysql_db,
        charset='utf8mb4',
        autocommit=False
    )

    try:
        cursor = conn.cursor()
        total_success = 0
        total_error = 0
        for sql_file, content in sql_files:
            log(f"执行 SQL: {sql_file.name}")
            statements = _parse_sql_statements(content)

            success_count = 0
            error_count = 0
            for stmt in statements:
                try:
                    cursor.execute(stmt)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"SQL 执行失败: {e}\n语句: {stmt[:100]}...")

            log(f"  ✅ 成功: {success_count} 条, ⚠️ 失败: {error_count} 条")
            total_success += success_count
            total_error += error_count

        conn.commit()
        cursor.close()
        log(f"✅ 床头卡脚本升级完成！共成功: {total_success} 条, 失败: {total_error} 条")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"床头卡脚本升级失败: {e}")
    finally:
        conn.close()


# ==============================
# GUI
# ==============================
class WardUpgradeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("病房前端一键升级工具")
        self.root.geometry("720x780")
        self.root.minsize(650, 630)

        self.config = load_config()
        self.create_widgets()
        self._load_ui_from_config()

    def create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=BOTH, expand=True)

        # ========== 服务器配置 ==========
        frame_server = ttk.LabelFrame(main, text="🖥️ 服务器配置", padding=8)
        frame_server.pack(fill=X, pady=(0, 8))

        ttk.Label(frame_server, text="服务器地址:").grid(row=0, column=0, sticky=W, pady=3)
        self.server_var = StringVar()
        self.server_combo = ttk.Combobox(frame_server, textvariable=self.server_var, width=30, state="normal")
        self.server_combo.grid(row=0, column=1, padx=5, pady=3, sticky=EW)
        self.server_combo.bind("<<ComboboxSelected>>", self._on_server_selected)
        self.server_combo.bind("<KeyRelease>", self._on_server_selected)

        ttk.Label(frame_server, text="连接用户:").grid(row=1, column=0, sticky=W, pady=3)
        self.ssh_user_var = StringVar(value="root")
        self.ssh_user_combo = ttk.Combobox(frame_server, textvariable=self.ssh_user_var, width=15, state="normal",
                                           values=["root", "yahua"])
        self.ssh_user_combo.grid(row=1, column=1, padx=5, pady=3, sticky=W)
        ttk.Label(frame_server, text="(默认root，可选择yahua或手动输入)", foreground="gray").grid(row=1, column=2, sticky=W)

        ttk.Label(frame_server, text="SSH密码:").grid(row=2, column=0, sticky=W, pady=3)
        self.pwd_var = StringVar()
        ttk.Entry(frame_server, textvariable=self.pwd_var, width=30).grid(row=2, column=1, padx=5, pady=3, sticky=EW)
        ttk.Label(frame_server, text="(留空则自动尝试默认密码)", foreground="gray").grid(row=2, column=2, sticky=W)

        frame_server.columnconfigure(1, weight=1)

        # ========== 升级目录 ==========
        frame_dir = ttk.LabelFrame(main, text="📁 升级文件目录", padding=8)
        frame_dir.pack(fill=X, pady=(0, 8))

        self.upgrade_dir_var = StringVar()
        ttk.Entry(frame_dir, textvariable=self.upgrade_dir_var, width=55).grid(row=0, column=0, padx=(0, 5), sticky=EW)
        ttk.Button(frame_dir, text="浏览...", command=self._select_upgrade_dir).grid(row=0, column=1)
        frame_dir.columnconfigure(0, weight=1)

        # ========== 升级选项 ==========
        frame_options = ttk.LabelFrame(main, text="📋 升级选项（多选）", padding=8)
        frame_options.pack(fill=X, pady=(0, 8))

        self.opt_web = BooleanVar(value=True)
        self.opt_chuangtou = BooleanVar(value=False)
        self.opt_chuangpang = BooleanVar(value=False)
        self.opt_kanban = BooleanVar(value=False)
        self.opt_bedcard_sql = BooleanVar(value=False)
        self.opt_menu_sql = BooleanVar(value=False)

        options = [
            (self.opt_web, "Web 前端", 0, 0),
            (self.opt_chuangtou, "床头", 0, 1),
            (self.opt_chuangpang, "床旁", 0, 2),
            (self.opt_kanban, "看板", 1, 0),
            (self.opt_bedcard_sql, "床头卡脚本", 1, 1),
            (self.opt_menu_sql, "菜单脚本", 1, 2),
        ]
        for var, text, r, c in options:
            ttk.Checkbutton(frame_options, text=text, variable=var).grid(row=r, column=c, sticky=W, padx=10, pady=3)

        # ========== MySQL 配置 ==========
        frame_mysql = ttk.LabelFrame(main, text="🗄️ MySQL 配置（菜单/脚本升级时需要）", padding=8)
        frame_mysql.pack(fill=X, pady=(0, 8))

        ttk.Label(frame_mysql, text="MySQL地址:").grid(row=0, column=0, sticky=W, pady=3)
        self.mysql_host_var = StringVar()
        ttk.Entry(frame_mysql, textvariable=self.mysql_host_var, width=20).grid(row=0, column=1, padx=5, pady=3, sticky=EW)

        ttk.Label(frame_mysql, text="端口:").grid(row=0, column=2, sticky=W, pady=3, padx=(10, 0))
        self.mysql_port_var = StringVar(value="3306")
        ttk.Entry(frame_mysql, textvariable=self.mysql_port_var, width=8).grid(row=0, column=3, padx=5, pady=3, sticky=W)

        ttk.Label(frame_mysql, text="数据库:").grid(row=1, column=0, sticky=W, pady=3)
        self.mysql_db_var = StringVar(value="YHDB")
        ttk.Entry(frame_mysql, textvariable=self.mysql_db_var, width=20).grid(row=1, column=1, padx=5, pady=3, sticky=EW)

        ttk.Label(frame_mysql, text="密码:").grid(row=1, column=2, sticky=W, pady=3, padx=(10, 0))
        self.mysql_pwd_var = StringVar()
        ttk.Entry(frame_mysql, textvariable=self.mysql_pwd_var, width=20).grid(row=1, column=3, padx=5, pady=3, sticky=EW, columnspan=2)
        ttk.Label(frame_mysql, text="(留空则自动尝试默认密码)", foreground="gray").grid(row=1, column=5, sticky=W)

        frame_mysql.columnconfigure(1, weight=1)

        # ========== 操作按钮 ==========
        frame_btn = ttk.Frame(main)
        frame_btn.pack(fill=X, pady=(0, 8))

        ttk.Button(frame_btn, text="💾 保存配置", command=self._save_config).pack(side=LEFT, padx=(0, 10))
        self.btn_start = ttk.Button(frame_btn, text="🚀 开始升级", command=self._start_upgrade)
        self.btn_start.pack(side=LEFT)

        # ========== 进度条 ==========
        self.progress = ttk.Progressbar(main, mode='indeterminate')
        self.progress.pack(fill=X, pady=(0, 5))

        # ========== 日志区域 ==========
        frame_log = ttk.LabelFrame(main, text="📝 升级日志", padding=5)
        frame_log.pack(fill=BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(frame_log, state=DISABLED, wrap=WORD, height=10, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

    # ---------- 事件处理 ----------
    def _on_server_selected(self, event=None):
        host = self.server_var.get().strip()
        servers = self.config.get("servers", {})
        if host in servers:
            self.pwd_var.set(servers[host].get("ssh_password", ""))
            self.ssh_user_var.set(servers[host].get("ssh_user", "root"))
        # 服务器地址变更时，MySQL 地址自动同步
        self.mysql_host_var.set(host)

    def _select_upgrade_dir(self):
        d = filedialog.askdirectory(title="选择升级文件目录")
        if d:
            self.upgrade_dir_var.set(d)

    def _load_ui_from_config(self):
        # 服务器列表
        servers = self.config.get("servers", {})
        server_list = list(servers.keys())
        self.server_combo['values'] = server_list
        last = self.config.get("last_server", "")
        if last:
            self.server_var.set(last)
            if last in servers:
                self.pwd_var.set(servers[last].get("ssh_password", ""))
                self.ssh_user_var.set(servers[last].get("ssh_user", self.config.get("ssh_user", "root")))

        # 升级目录
        self.upgrade_dir_var.set(self.config.get("upgrade_dir", ""))

        # SSH 用户
        self.ssh_user_var.set(self.config.get("ssh_user", "root"))

        # MySQL
        self.mysql_host_var.set(self.config.get("mysql_host", ""))
        self.mysql_port_var.set(str(self.config.get("mysql_port", 3306)))
        self.mysql_db_var.set(self.config.get("mysql_db", "YHDB"))
        self.mysql_pwd_var.set(self.config.get("mysql_password", ""))

        self._log("配置已加载")

    def _save_config(self):
        self.config["last_server"] = self.server_var.get().strip()
        self.config["ssh_user"] = self.ssh_user_var.get().strip()
        self.config["upgrade_dir"] = self.upgrade_dir_var.get().strip()
        self.config["mysql_host"] = self.mysql_host_var.get().strip()
        self.config["mysql_port"] = int(self.mysql_port_var.get() or 3306)
        self.config["mysql_db"] = self.mysql_db_var.get().strip()
        self.config["mysql_password"] = self.mysql_pwd_var.get().strip()

        # 保存当前服务器的 SSH 密码
        host = self.server_var.get().strip()
        if host:
            if "servers" not in self.config:
                self.config["servers"] = {}
            if host not in self.config["servers"]:
                self.config["servers"][host] = {}
            self.config["servers"][host]["ssh_password"] = self.pwd_var.get().strip()
            self.config["servers"][host]["ssh_user"] = self.ssh_user_var.get().strip()

        save_config(self.config)
        self.server_combo['values'] = list(self.config.get("servers", {}).keys())
        messagebox.showinfo("成功", "配置已保存！")

    def _log(self, message):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    # ---------- 密码测试 ----------
    def _get_ssh_user(self):
        """获取当前 SSH 连接用户名"""
        return self.ssh_user_var.get().strip() or "root"

    def _test_ssh_password(self, host):
        """测试 SSH密码，返回成功的密码或None"""
        username = self._get_ssh_user()
        pwd = self.pwd_var.get().strip()
        if pwd:
            try:
                client = get_ssh_client(host, username=username, password=pwd, timeout=8)
                client.close()
                return pwd
            except Exception:
                self._log(f"用户 {username} 输入的密码连接失败")
                return None

        for p in DEFAULT_SSH_PASSWORDS:
            try:
                self._log(f"尝试用户 {username} 默认密码: {p}")
                self.root.update_idletasks()
                client = get_ssh_client(host, username=username, password=p, timeout=8)
                client.close()
                self._log(f"✅ 密码验证成功: {p}")
                self.pwd_var.set(p)
                # 保存到配置
                if "servers" not in self.config:
                    self.config["servers"] = {}
                if host not in self.config["servers"]:
                    self.config["servers"][host] = {}
                self.config["servers"][host]["ssh_password"] = p
                self.config["servers"][host]["ssh_user"] = username
                save_config(self.config)
                return p
            except Exception:
                continue
        return None

    def _test_mysql_password(self, host, port):
        """测试MySQL密码，返回成功的密码或None"""
        pwd = self.mysql_pwd_var.get().strip()
        if pwd:
            try:
                conn = pymysql.connect(host=host, port=int(port), user='root', password=pwd, connect_timeout=8)
                conn.close()
                return pwd
            except Exception:
                self._log(f"MySQL 输入的密码连接失败")
                return None

        for p in DEFAULT_MYSQL_PASSWORDS:
            try:
                self._log(f"尝试 MySQL 默认密码: {p}")
                self.root.update_idletasks()
                conn = pymysql.connect(host=host, port=int(port), user='root', password=p, connect_timeout=8)
                conn.close()
                self._log(f"✅ MySQL 密码验证成功: {p}")
                self.mysql_pwd_var.set(p)
                self.config["mysql_password"] = p
                save_config(self.config)
                return p
            except Exception:
                continue
        return None

    # ---------- 开始升级 ----------
    def _start_upgrade(self):
        host = self.server_var.get().strip()
        upgrade_dir = self.upgrade_dir_var.get().strip()

        if not host:
            messagebox.showerror("错误", "请输入服务器地址！")
            return
        if not upgrade_dir or not Path(upgrade_dir).is_dir():
            messagebox.showerror("错误", "请选择有效的升级文件目录！")
            return

        # 获取选中的升级项
        selected = []
        if self.opt_web.get():
            selected.append("web")
        if self.opt_chuangtou.get():
            selected.append("床头")
        if self.opt_chuangpang.get():
            selected.append("床旁")
        if self.opt_kanban.get():
            selected.append("看板")
        if self.opt_bedcard_sql.get():
            selected.append("床头卡脚本")
        if self.opt_menu_sql.get():
            selected.append("菜单脚本")

        if not selected:
            messagebox.showerror("错误", "请至少选择一项升级内容！")
            return

        # 如果需要菜单脚本升级，验证 MySQL
        need_mysql = "菜单脚本" in selected or "床头卡脚本" in selected
        mysql_pwd = None
        if need_mysql:
            mysql_host = self.mysql_host_var.get().strip() or host
            mysql_port = self.mysql_port_var.get().strip() or "3306"
            self._log(f"验证 MySQL 连接...")
            mysql_pwd = self._test_mysql_password(mysql_host, mysql_port)
            if not mysql_pwd:
                messagebox.showerror("错误", "MySQL 所有密码均连接失败，请手动输入正确密码！")
                return

        # 如果需要 Web 升级，查找升级包
        web_package = None
        if "web" in selected:
            for name in ["web.zip", "web.tar.gz", "web.tgz", "dist.tar.gz"]:
                p = Path(upgrade_dir) / name
                if p.exists():
                    web_package = str(p)
                    self._log(f"找到 Web 升级包: {name}")
                    break
            if not web_package:
                # 在主线程弹出文件选择
                web_package = filedialog.askopenfilename(
                    title="未自动找到 Web 升级包，请手动选择",
                    filetypes=[("压缩包", "*.zip *.tar.gz *.tgz"), ("所有文件", "*.*")],
                    initialdir=upgrade_dir
                )
                if not web_package:
                    messagebox.showerror("错误", "未选择 Web 升级包，取消升级！")
                    return

        # 如果需要看板升级，查找看板升级包
        kanban_package = None
        if "看板" in selected:
            # 查找 ntv-*.tar.gz 格式的包
            ntv_packages = sorted(Path(upgrade_dir).glob("ntv-*.tar.gz"))
            if ntv_packages:
                kanban_package = str(ntv_packages[-1])  # 取最新的
                self._log(f"找到看板升级包: {ntv_packages[-1].name}")
            else:
                # 未自动找到，弹出文件选择
                kanban_package = filedialog.askopenfilename(
                    title="未自动找到看板升级包(ntv-*.tar.gz)，请手动选择",
                    filetypes=[("压缩包", "*.tar.gz *.tgz *.zip"), ("所有文件", "*.*")],
                    initialdir=upgrade_dir
                )
                if not kanban_package:
                    messagebox.showerror("错误", "未选择看板升级包，取消升级！")
                    return

        # 床头/床旁升级源查找
        device_sources = {}
        for label, dir_names, pkg_prefix, remote in [
            ("床头", ["床头", "bedhead"], "bedhead", "/home/data/web/a10/bedhead"),
            ("床旁", ["床旁", "bedside"], "bedside", "/home/data/web/a10/bedside"),
        ]:
            if label not in selected:
                continue
            # 先查找本地目录
            found_dir = None
            for dn in dir_names:
                d = Path(upgrade_dir) / dn
                if d.is_dir():
                    found_dir = str(d)
                    self._log(f"找到 {label} 本地目录: {dn}")
                    break
            if found_dir:
                device_sources[label] = ("dir", found_dir, remote)
            else:
                # 查找压缩包
                packages = sorted(Path(upgrade_dir).glob(f"{pkg_prefix}-*.tar.gz"))
                if packages:
                    device_sources[label] = ("package", str(packages[-1]), remote)
                    self._log(f"找到 {label} 升级包: {packages[-1].name}")
                else:
                    pkg = filedialog.askopenfilename(
                        title=f"未自动找到 {label} 升级包({pkg_prefix}-*.tar.gz)，请手动选择",
                        filetypes=[("压缩包", "*.tar.gz *.tgz *.zip"), ("所有文件", "*.*")],
                        initialdir=upgrade_dir
                    )
                    if not pkg:
                        messagebox.showerror("错误", f"未选择 {label} 升级包，取消升级！")
                        return
                    device_sources[label] = ("package", pkg, remote)

        # 测试 SSH 密码
        self._log(f"验证 SSH 连接...")
        ssh_pwd = self._test_ssh_password(host)
        if not ssh_pwd:
            messagebox.showerror("错误", "SSH 所有密码均连接失败，请手动输入正确密码！")
            return

        # 保存配置
        self._save_config_silent()

        # 开始升级
        self.btn_start.config(state=DISABLED)
        self.progress.start(10)
        self._log(f"开始升级: {', '.join(selected)}")

        mysql_config = {
            "host": self.mysql_host_var.get().strip() or host,
            "port": int(self.mysql_port_var.get().strip() or 3306),
            "db": self.mysql_db_var.get().strip() or "YHDB",
            "password": mysql_pwd or ""
        }

        ssh_user = self._get_ssh_user()
        thread = threading.Thread(
            target=self._run_upgrade,
            args=(host, ssh_user, ssh_pwd, upgrade_dir, selected, web_package, kanban_package, device_sources, mysql_config, need_mysql),
            daemon=True
        )
        thread.start()

    def _save_config_silent(self):
        """静默保存配置"""
        self.config["last_server"] = self.server_var.get().strip()
        self.config["ssh_user"] = self.ssh_user_var.get().strip()
        self.config["upgrade_dir"] = self.upgrade_dir_var.get().strip()
        self.config["mysql_host"] = self.mysql_host_var.get().strip()
        self.config["mysql_port"] = int(self.mysql_port_var.get().strip() or 3306)
        self.config["mysql_db"] = self.mysql_db_var.get().strip()
        self.config["mysql_password"] = self.mysql_pwd_var.get().strip()

        host = self.server_var.get().strip()
        if host:
            if "servers" not in self.config:
                self.config["servers"] = {}
            if host not in self.config["servers"]:
                self.config["servers"][host] = {}
            self.config["servers"][host]["ssh_password"] = self.pwd_var.get().strip()
            self.config["servers"][host]["ssh_user"] = self.ssh_user_var.get().strip()

        save_config(self.config)
        self.server_combo['values'] = list(self.config.get("servers", {}).keys())

    def _run_upgrade(self, host, ssh_user, ssh_pwd, upgrade_dir, selected, web_package, kanban_package, device_sources, mysql_config, need_mysql):
        """后台执行升级"""
        try:
            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            for item in selected:
                if item == "web":
                    log("=" * 40)
                    log("📦 开始 Web 前端升级...")
                    do_web_upgrade(host, ssh_user, ssh_pwd, web_package, log)

                elif item == "菜单脚本":
                    if need_mysql and mysql_config["password"]:
                        log("=" * 40)
                        log("📋 开始菜单脚本升级...")
                        do_menu_upgrade(host, mysql_config, upgrade_dir, log)
                    else:
                        log("⏭️ 跳过菜单脚本升级（未配置 MySQL）")

                elif item == "看板":
                    log("=" * 40)
                    log("📺 开始看板升级...")
                    do_kanban_upgrade(host, ssh_user, ssh_pwd, kanban_package, log)

                elif item == "床头":
                    log("=" * 40)
                    log("🛏️ 开始床头升级...")
                    src_type, src_path, remote = device_sources["床头"]
                    do_device_upgrade(host, ssh_user, ssh_pwd, "bedhead", remote, src_type, src_path, log)

                elif item == "床旁":
                    log("=" * 40)
                    log("🛏️ 开始床旁升级...")
                    src_type, src_path, remote = device_sources["床旁"]
                    do_device_upgrade(host, ssh_user, ssh_pwd, "bedside", remote, src_type, src_path, log)

                elif item == "床头卡脚本":
                    if need_mysql and mysql_config["password"]:
                        log("=" * 40)
                        log("🗂️ 开始床头卡脚本升级...")
                        do_bedcard_sql_upgrade(mysql_config, upgrade_dir, log)
                    else:
                        log("⏭️ 跳过床头卡脚本升级（未配置 MySQL）")

            log("=" * 40)
            log("🎉 所有升级任务完成！")
            self.root.after(0, lambda: self._show_toast("升级完成", f"服务器 {host} 升级完成！", "success"))

        except Exception as e:
            error_msg = f"升级失败：{str(e)}"
            self.root.after(0, lambda: self._show_toast("升级失败", error_msg, "error"))
            logger.exception("Upgrade failed")
        finally:
            self.root.after(0, self._upgrade_finished)

    def _upgrade_finished(self):
        self.progress.stop()
        self.btn_start.config(state=NORMAL)

    def _show_toast(self, title, message, level="info", duration_ms=180000):
        """屏幕右下角弹出一条消息提醒，duration_ms 后自动消失（默认3分钟）"""
        toast = Toplevel(self.root)
        toast.withdraw()  # 先隐藏，定位后再显示
        toast.overrideredirect(True)  # 无边框
        toast.attributes('-topmost', True)

        # 颜色和图标根据级别设置
        colors = {
            "success": ("#2e7d32", "#e8f5e9", "✅"),
            "error":   ("#c62828", "#ffebee", "❌"),
            "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
        }
        fg, bg, icon = colors.get(level, colors["info"])

        toast.configure(bg=bg)

        # 标题行
        header = Frame(toast, bg=bg)
        header.pack(fill=X, padx=10, pady=(8, 0))
        Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
              fg=fg, bg=bg).pack(side=LEFT)
        Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg,
              cursor="hand2").pack(side=RIGHT)
        header.winfo_children()[-1].bind("<Button-1>", lambda e: toast.destroy())

        # 消息内容
        Label(toast, text=message, font=("Microsoft YaHei UI", 10),
              fg="#333", bg=bg, wraplength=320, justify=LEFT).pack(padx=12, pady=(4, 10), anchor=W)

        # 计算屏幕右下角位置
        toast.update_idletasks()
        w, h = toast.winfo_width(), toast.winfo_height()
        sx = toast.winfo_screenwidth()
        sy = toast.winfo_screenheight()
        x = sx - w - 20
        y = sy - h - 60  # 避开任务栏
        toast.geometry(f"+{x}+{y}")
        toast.deiconify()

        # 自动消失
        toast.after(duration_ms, toast.destroy)


# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    missing = []
    if not paramiko:
        missing.append("paramiko")
    if not pymysql:
        missing.append("pymysql")

    if missing:
        root = Tk()
        root.withdraw()
        msg = "缺少依赖库，请运行以下命令安装：\n\npip install " + " ".join(missing)
        messagebox.showerror("依赖缺失", msg)
        root.destroy()
        exit(1)

    root = Tk()
    app = WardUpgradeGUI(root)
    root.mainloop()
