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


# ==============================
# Web 升级逻辑
# ==============================
def do_web_upgrade(host, password, web_package_path, log):
    """Web 前端升级：备份 → 清理 → 上传"""
    log("正在连接服务器...")
    with get_ssh_client(host, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 1. 备份
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{WEB_REMOTE_PATH}/backup_{timestamp}"
        ensure_remote_dir(sftp, backup_dir, log)
        log(f"备份目录: {backup_dir}")

        for item in WEB_BACKUP_ITEMS:
            remote_item = f"{WEB_REMOTE_PATH}/{item}"
            try:
                sftp.stat(remote_item)
                log(f"备份: {item}")
                # 通过 SSH 命令复制（保留权限）
                stdin, stdout, stderr = ssh.exec_command(f"cp -r {remote_item} {backup_dir}/")
                stdout.channel.recv_exit_status()
            except IOError:
                log(f"跳过（不存在）: {item}")

        # 2. 删除原文件
        log("清理服务器文件...")
        for item in WEB_BACKUP_ITEMS:
            clear_remote_path(sftp, f"{WEB_REMOTE_PATH}/{item}")

        # 3. 解压并上传
        log("解压升级包...")
        with tempfile.TemporaryDirectory() as tmpdir:
            if web_package_path.endswith('.zip'):
                with zipfile.ZipFile(web_package_path, 'r') as zf:
                    zf.extractall(tmpdir)
            elif web_package_path.endswith('.tar.gz') or web_package_path.endswith('.tgz'):
                with tarfile.open(web_package_path, 'r:gz') as tf:
                    tf.extractall(tmpdir)
            else:
                raise ValueError(f"不支持的压缩格式: {web_package_path}")

            # 查找解压后的 web 内容目录
            extracted = list(Path(tmpdir).iterdir())
            if len(extracted) == 1 and extracted[0].is_dir():
                web_content_dir = extracted[0]
            else:
                web_content_dir = Path(tmpdir)

            log(f"上传文件到 {WEB_REMOTE_PATH}...")
            upload_dir(sftp, str(web_content_dir), WEB_REMOTE_PATH, log)

        sftp.close()
    log("✅ Web 升级完成！")


# ==============================
# 菜单脚本升级逻辑
# ==============================
def do_menu_upgrade(host, mysql_config, upgrade_dir, log):
    """菜单脚本升级：执行 SQL 文件到 MySQL"""
    sql_files = []

    # 查找菜单相关的 SQL 文件
    for f in Path(upgrade_dir).iterdir():
        if f.is_file() and f.suffix.lower() == '.sql':
            name = f.name
            if '菜单' in name or '权限' in name:
                sql_files.append(f)

    if not sql_files:
        log("⚠️ 升级目录中未找到菜单相关 SQL 文件")
        return

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
# GUI
# ==============================
class WardUpgradeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("病房前端一键升级工具")
        self.root.geometry("720x750")
        self.root.minsize(650, 600)

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

        ttk.Label(frame_server, text="SSH密码:").grid(row=1, column=0, sticky=W, pady=3)
        self.pwd_var = StringVar()
        ttk.Entry(frame_server, textvariable=self.pwd_var, width=30).grid(row=1, column=1, padx=5, pady=3, sticky=EW)
        ttk.Label(frame_server, text="(留空则自动尝试默认密码)", foreground="gray").grid(row=1, column=2, sticky=W)

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

        # 升级目录
        self.upgrade_dir_var.set(self.config.get("upgrade_dir", ""))

        # MySQL
        self.mysql_host_var.set(self.config.get("mysql_host", ""))
        self.mysql_port_var.set(str(self.config.get("mysql_port", 3306)))
        self.mysql_db_var.set(self.config.get("mysql_db", "YHDB"))
        self.mysql_pwd_var.set(self.config.get("mysql_password", ""))

        self._log("配置已加载")

    def _save_config(self):
        self.config["last_server"] = self.server_var.get().strip()
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

        save_config(self.config)
        self.server_combo['values'] = list(self.config.get("servers", {}).keys())
        messagebox.showinfo("成功", "配置已保存！")

    def _log(self, message):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    # ---------- 密码测试 ----------
    def _test_ssh_password(self, host):
        """测试 SSH密码，返回成功的密码或None"""
        pwd = self.pwd_var.get().strip()
        if pwd:
            try:
                client = get_ssh_client(host, password=pwd, timeout=8)
                client.close()
                return pwd
            except Exception:
                self._log(f"输入的密码连接失败")
                return None

        for p in DEFAULT_SSH_PASSWORDS:
            try:
                self._log(f"尝试默认密码: {p}")
                self.root.update_idletasks()
                client = get_ssh_client(host, password=p, timeout=8)
                client.close()
                self._log(f"✅ 密码验证成功: {p}")
                self.pwd_var.set(p)
                # 保存到配置
                if "servers" not in self.config:
                    self.config["servers"] = {}
                if host not in self.config["servers"]:
                    self.config["servers"][host] = {}
                self.config["servers"][host]["ssh_password"] = p
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
            for name in ["web.zip", "web.tar.gz", "web.tgz"]:
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

        thread = threading.Thread(
            target=self._run_upgrade,
            args=(host, ssh_pwd, upgrade_dir, selected, web_package, mysql_config, need_mysql),
            daemon=True
        )
        thread.start()

    def _save_config_silent(self):
        """静默保存配置"""
        self.config["last_server"] = self.server_var.get().strip()
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

        save_config(self.config)
        self.server_combo['values'] = list(self.config.get("servers", {}).keys())

    def _run_upgrade(self, host, ssh_pwd, upgrade_dir, selected, web_package, mysql_config, need_mysql):
        """后台执行升级"""
        try:
            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            for item in selected:
                if item == "web":
                    log("=" * 40)
                    log("📦 开始 Web 前端升级...")
                    do_web_upgrade(host, ssh_pwd, web_package, log)

                elif item == "菜单脚本":
                    if need_mysql and mysql_config["password"]:
                        log("=" * 40)
                        log("📋 开始菜单脚本升级...")
                        do_menu_upgrade(host, mysql_config, upgrade_dir, log)
                    else:
                        log("⏭️ 跳过菜单脚本升级（未配置 MySQL）")

                elif item in ("床头", "床旁", "看板", "床头卡脚本"):
                    log("=" * 40)
                    log(f"⏭️ {item} 升级功能后续开发中...")

            log("=" * 40)
            log("🎉 所有升级任务完成！")
            self.root.after(0, lambda: messagebox.showinfo("成功", f"服务器 {host} 升级完成！"))

        except Exception as e:
            error_msg = f"升级失败：{str(e)}"
            self.root.after(0, lambda: messagebox.showerror("错误", error_msg))
            logger.exception("Upgrade failed")
        finally:
            self.root.after(0, self._upgrade_finished)

    def _upgrade_finished(self):
        self.progress.stop()
        self.btn_start.config(state=NORMAL)


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
