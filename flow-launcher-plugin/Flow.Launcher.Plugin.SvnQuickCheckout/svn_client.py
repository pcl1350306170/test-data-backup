# -*- coding: utf-8 -*-
"""SVN 命令行封装（复用 svn快速检出.pyw 的成熟实践）"""
import os
import subprocess
import threading

# SVN 公共参数（非交互式 + 信任自签名证书）
_SVN_COMMON_ARGS = [
    "--non-interactive",
    "--trust-server-cert",
]


def _decode_svn_output(data: bytes) -> str:
    """解码 SVN 输出：UTF-8 → GBK → UTF-8(replace) 三级回退"""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")


def run_svn_command(args: list, timeout: int = 60) -> tuple:
    """执行 svn 命令，返回 (returncode, stdout, stderr)"""
    env = os.environ.copy()
    env["SVN_SSL_NO_VERIFY"] = "1"
    try:
        proc = subprocess.Popen(
            ["svn"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            raw_out, raw_err = proc.communicate(timeout=timeout)
            return proc.returncode, _decode_svn_output(raw_out), _decode_svn_output(raw_err)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return -1, "", f"命令超时（{timeout}s）"
    except FileNotFoundError:
        return -2, "", "未找到 svn 命令，请确保已安装 SVN 客户端并加入 PATH"
    except Exception as e:
        return -3, "", str(e)


def list_dirs(url: str, username: str, password: str, timeout: int = 60) -> list:
    """列出指定 SVN URL 下的直接子目录名（不含文件）"""
    code, stdout, stderr = run_svn_command([
        "list", url,
        "--username", username,
        "--password", password,
        *_SVN_COMMON_ARGS,
    ], timeout=timeout)
    if code != 0:
        return []
    # svn list 中目录行以 / 结尾，据此过滤文件
    return [
        line.rstrip("/")
        for line in (stdout or "").strip().splitlines()
        if line.strip().endswith("/")
    ]


def svn_info(url: str, username: str, password: str) -> bool:
    """判断 SVN 上某目录是否存在"""
    code, _, _ = run_svn_command([
        "info", url,
        "--username", username, "--password", password,
        *_SVN_COMMON_ARGS,
    ], timeout=30)
    return code == 0


def svn_mkdir(url: str, username: str, password: str, msg: str) -> tuple:
    """在 SVN 上创建目录，返回 (ok, 错误信息)"""
    code, out, err = run_svn_command([
        "mkdir", url, "-m", msg,
        "--username", username, "--password", password,
        *_SVN_COMMON_ARGS,
    ], timeout=60)
    return code == 0, (err or out)


def svn_checkout(url: str, local_path: str, username: str, password: str) -> tuple:
    """检出 SVN 目录到本地，返回 (ok, 错误信息)"""
    code, out, err = run_svn_command([
        "checkout", url, str(local_path),
        "--username", username, "--password", password,
        *_SVN_COMMON_ARGS,
    ], timeout=600)
    return code == 0, (err or out)


def extract_order_no(text: str) -> str:
    """从文本开头提取编号 YYYY-NNNN，无则返回空串"""
    import re
    m = re.match(r"^(\d{4}-\d{4})", text.strip())
    return m.group(1) if m else ""


def find_matching_dir(dirs: list, order_no: str) -> str:
    """在目录名列表中查找以指定编号（或前缀）开头的目录"""
    for d in dirs:
        if d[:len(order_no)] == order_no:
            return d
    return ""


class SvnBrowser:
    """懒加载的 SVN 目录浏览器

    一级目录数量可达数百个，因此不预先递归全部两层，而是：
    - 一级目录：整类一次性拉取（单个 svn list，秒级）并缓存
    - 二级目录：仅对命中关键字的一级目录按需展开并缓存
    """

    def __init__(self, cache_seconds: int = 300, max_expand: int = 15):
        self.cache_seconds = cache_seconds
        self.max_expand = max_expand        # 单次查询最多展开的一级目录数
        self._l1_cache = {}                 # type_name -> (timestamp, [name])
        self._l2_cache = {}                 # (type_name, l1_name) -> (timestamp, [name])
        self._lock = threading.Lock()

    # ── 一级目录 ──────────────────────────────────────

    def get_level1(self, type_name: str, cfg: dict) -> list:
        """返回一级目录名列表（带 TTL 缓存，阻塞拉取）"""
        import time
        with self._lock:
            cached = self._l1_cache.get(type_name)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1]
        base_url = cfg.get("svn_base_url", "").rstrip("/")
        names = list_dirs(base_url, cfg.get("username", ""), cfg.get("password", ""))
        with self._lock:
            self._l1_cache[type_name] = (time.time(), names)
        return names

    # ── 二级目录 ──────────────────────────────────────

    def get_level2(self, type_name: str, l1_name: str, cfg: dict) -> list:
        """返回指定一级目录下的二级目录名列表（带 TTL 缓存，阻塞拉取）"""
        import time
        key = (type_name, l1_name)
        with self._lock:
            cached = self._l2_cache.get(key)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1]
        base_url = cfg.get("svn_base_url", "").rstrip("/")
        url1 = f"{base_url}/{l1_name}"
        names = list_dirs(url1, cfg.get("username", ""), cfg.get("password", ""))
        with self._lock:
            self._l2_cache[key] = (time.time(), names)
        return names

    # ── 缓存管理 ──────────────────────────────────

    def resolve_order(self, type_name: str, cfg: dict, order_name: str) -> dict:
        """基于已缓存的一/二级目录列表解析订单目标（尽量不发额外请求）

        返回字段：exists/order_name/order_no/target_url/local_path/
                  need_hospital/hospital_url/hospital_name
        存在性判定复用浏览时的 svn list 缓存，避免逐字符敲键时反复请求。
        """
        import os as _os
        base = cfg.get("svn_base_url", "").rstrip("/")
        local_dir = cfg.get("local_checkout_dir", "")
        order_no = extract_order_no(order_name)
        l1 = self.get_level1(type_name, cfg)

        if type_name == "病房":
            hospital_name = order_name[9:] if len(order_name) > 9 else order_name
            hospital = hospital_name if hospital_name in l1 else find_matching_dir(l1, hospital_name[:9])
            need_hospital = not hospital
            hospital = hospital or hospital_name
            hospital_url = f"{base}/{hospital}"
            if need_hospital:
                exists, final_order = False, order_name
            else:
                l2 = self.get_level2(type_name, hospital, cfg)
                matched = find_matching_dir(l2, order_no) if order_no else ""
                exists = bool(matched)
                final_order = matched or order_name
            target_url = f"{hospital_url}/{final_order}"
            local_path = _os.path.join(local_dir, final_order) if local_dir else ""
            return {
                "exists": exists, "order_name": final_order, "order_no": order_no,
                "target_url": target_url, "local_path": local_path,
                "need_hospital": need_hospital, "hospital_url": hospital_url,
                "hospital_name": hospital,
            }

        # 门诊（默认）：一级目录
        matched = find_matching_dir(l1, order_no) if order_no else ""
        exists = bool(matched)
        final_order = matched or order_name
        target_url = f"{base}/{final_order}"
        local_path = _os.path.join(local_dir, final_order) if local_dir else ""
        return {
            "exists": exists, "order_name": final_order, "order_no": order_no,
            "target_url": target_url, "local_path": local_path,
            "need_hospital": False, "hospital_url": "", "hospital_name": "",
        }

    def peek_level1(self, type_name: str):
        """只读返回已缓存的一级目录名（不触发拉取），无缓存返回 None"""
        with self._lock:
            cached = self._l1_cache.get(type_name)
            if not cached:
                return None
            return cached[1]

    def invalidate(self, type_name: str = None):
        """清除指定分类（或全部）缓存，强制下次重新拉取"""
        with self._lock:
            if type_name is None:
                self._l1_cache.clear()
                self._l2_cache.clear()
                return
            self._l1_cache.pop(type_name, None)
            for key in [k for k in self._l2_cache if k[0] == type_name]:
                self._l2_cache.pop(key, None)
