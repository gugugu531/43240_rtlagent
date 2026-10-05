#!/usr/bin/env python3
"""Launch and destroy AMD Radeon Cloud GPU instances from the command line.

    ./cloud.py me                       account, credits (the API key is never printed)
    ./cloud.py templates                your templates and the images you can use
    ./cloud.py up [--max-minutes N]     launch (or adopt) the instance, wait until ready
    ./cloud.py status                   what the platform says about the instance
    ./cloud.py down                     destroy the instance, stop the watchdog
    ./cloud.py session [--max-minutes N] -- <command...>
                                        up -> start vLLM -> tunnel -> run command
                                        -> tunnel down -> destroy, whatever happens

An instance bills for every minute it exists, used or not. Three guards against
an instance left running:

  1. `session` destroys the instance in a finally block, including on Ctrl-C,
     SIGTERM and failures of the command.
  2. `up` starts a detached watchdog that destroys the instance after
     --max-minutes, even if this script or the shell that ran it dies.
  3. The platform's own idle timeout and maximum lifetime (a last resort).

The guards only cover instances this script launched. An instance that already
existed (launched from the console, say) is adopted but never destroyed by
`session` -- unless --own says it is ours, or use `down` explicitly.

Credentials. The docs say the Platform API takes the API key (RC_API_KEY). The
China site (developer.amd.com.cn/radeon) does not: its Platform API answers
"Login required" to the key in any header, and only takes the browser login
session. Copy the Cookie header from a signed-in console request into
RC_COOKIE. The API key still works there for the model API only.

Launch verification. The China console may ask for an email code (behind a
captcha) before a launch; a script cannot answer that. `up` then stops and
says so: launch from the console, then `up --own` / `session --own` to take
the instance over, so the watchdog and the final destroy still apply.

Platform API: https://amd-aim.github.io/radeon-cloud-docs/api/instances/
Configuration comes from remote.env (RC_*); see remote.env.example.
Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cloud.state")
KNOWN_HOSTS = os.path.join(HERE, "cloud_known_hosts")

# China site. The Global site is https://radeon-global.anruicloud.com; accounts,
# keys and credits do not carry across the two.
DEFAULT_API_BASE = "https://developer.amd.com.cn/radeon"


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------- config

def load_env() -> dict:
    """KEY=VALUE lines of remote.env, without running it through a shell."""
    env = {}
    try:
        with open(os.path.join(HERE, "remote.env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.split(" #", 1)[0].strip().strip("'\"")
    except OSError:
        pass
    return env


class Config:
    def __init__(self) -> None:
        env = load_env()
        get = lambda k, d="": os.environ.get(k) or env.get(k) or d  # noqa: E731
        self.api_base = get("RC_API_BASE", DEFAULT_API_BASE).rstrip("/")
        self.api_key = get("RC_API_KEY")
        self.cookie = get("RC_COOKIE")
        self.template_id = get("RC_TEMPLATE_ID")
        self.gpu_count = int(get("RC_GPU_COUNT", "1"))
        self.max_minutes = float(get("RC_MAX_MINUTES", "180"))
        self.ready_timeout = float(get("RC_READY_TIMEOUT", "1200"))
        self.ssh_timeout = float(get("RC_SSH_TIMEOUT", "600"))
        self.ssh_opts = get("REMOTE_SSH_OPTS")

    def need_key(self) -> None:
        if not self.api_key and not self.cookie:
            sys.exit("✗ 没有登录凭据：在 remote.env 中设置 RC_COOKIE（中国站点）或 RC_API_KEY（Global 站点）")


# ---------------------------------------------------------------------- api

class ApiError(RuntimeError):
    def __init__(self, status: int, detail, retry_after: str | None = None):
        # detail is a string, or a dict such as {"code": "...", "message": "..."}
        code = detail.get("code") if isinstance(detail, dict) else None
        msg = (detail.get("message") or detail) if isinstance(detail, dict) else detail
        super().__init__(f"HTTP {status}: {str(msg)[:300]}")
        self.status, self.code, self.retry_after = status, code, retry_after


def api(cfg: Config, method: str, path: str, body: dict | None = None,
        timeout: float = 60) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "fpgachina-cloud/1"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    if cfg.cookie:
        headers["Cookie"] = cfg.cookie
        # Cookie-authenticated writes (launch, destroy) are refused with
        # "403 Invalid request origin" unless they come from the console's own
        # origin, as a browser would send them.
        origin = "/".join(cfg.api_base.split("/")[:3])
        headers["Origin"] = origin
        headers["Referer"] = cfg.api_base + "/"
    req = urllib.request.Request(
        path if path.startswith("http") else cfg.api_base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except (ValueError, AttributeError):
            detail = raw
        raise ApiError(exc.code, detail, exc.headers.get("Retry-After")) from None
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise ApiError(0, f"响应不是 JSON：{raw[:200]}") from None


# The console tracks vLLM-type instances ("inference") on separate endpoints:
# /api/inference/current for status and destroy. Notebook-type instances, the
# kind used here (SSH in, run serve/vllm.sh), use /api/notebook/*.

def status(cfg: Config) -> dict:
    s = api(cfg, "GET", "/api/notebook/status")
    if s.get("instance_id") or s.get("status") not in (None, "not_found"):
        return s
    try:
        inf = api(cfg, "GET", "/api/inference/current")
    except ApiError:
        return s
    if isinstance(inf, dict) and inf.get("instance_id"):
        inf.setdefault("status", "unknown")
        inf["lifecycle"] = "inference"
        return inf
    return s


def destroy(cfg: Config) -> dict:
    # Safe to call twice: "No active instance found" comes back as success=false.
    r = api(cfg, "DELETE", "/api/notebook/current")
    if r.get("success"):
        return r
    try:
        r2 = api(cfg, "DELETE", "/api/inference/current")
    except ApiError:
        return r
    return r2 if isinstance(r2, dict) and r2.get("success") else r


# -------------------------------------------------------------------- state

def read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clear_state() -> None:
    state = read_state()
    pid = state.get("watchdog_pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for path in (STATE, KNOWN_HOSTS):
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------------ actions

def cmd_me(cfg: Config, _args) -> int:
    cfg.need_key()
    me = api(cfg, "GET", "/api/me")
    log(f"账号       {me.get('email')}（id {me.get('id')}）")
    log(f"已验证     {me.get('verified')}")
    log(f"余额       {me.get('credits')} credits")
    log(f"SSH 公钥   {'已设置' if me.get('ssh_public_key') else '未设置（无法 SSH 登录实例）'}")
    return 0


def cmd_templates(cfg: Config, _args) -> int:
    cfg.need_key()
    data = api(cfg, "GET", "/api/profile/templates")
    log("我的模板：")
    for t in data.get("templates", []):
        log(f"  id={t.get('id'):<6} {t.get('title')!s:<30} type={t.get('instance_type')}"
            f"  ssh={'开' if t.get('ssh_enabled') else '关'}  image={t.get('image')}")
    log("可用镜像：")
    for i in data.get("images", []):
        if i.get("enabled"):
            log(f"  {i.get('image')}  ({i.get('name')})")
    return 0


def cmd_status(cfg: Config, _args) -> int:
    cfg.need_key()
    s = status(cfg)
    state = read_state()
    log(f"平台状态   {s.get('status')}  ready={s.get('ready')}  {s.get('message', '')}")
    if s.get("instance_id"):
        log(f"实例       {s['instance_id']}")
    if s.get("ssh_host"):
        log(f"SSH        {s.get('ssh_username')}@{s['ssh_host']} -p {s.get('ssh_port')}")
    if state:
        owned = "本脚本启动" if state.get("launched_by_us") else "已存在的实例（不会被自动销毁）"
        started = time.strftime("%H:%M:%S", time.localtime(state.get("started", 0)))
        log(f"本地记录   {state.get('instance_id')}，{owned}，{started} 启动")
        if state.get("deadline"):
            left = (state["deadline"] - time.time()) / 60
            log(f"看门狗     {left:.0f} 分钟后自动销毁（进程号 {state.get('watchdog_pid')}）")
    return 0


def resolve(cfg: Config, url: str) -> str:
    """status_url comes back as a full URL, as /radeon/api/..., or as /api/..."""
    if url.startswith("http"):
        return url
    origin = "/".join(cfg.api_base.split("/")[:3])
    base_path = cfg.api_base[len(origin):]
    if base_path and url.startswith(base_path + "/"):
        return origin + url
    return cfg.api_base + url


def wait_job(cfg: Config, job_url: str, deadline: float) -> None:
    """A launch is an asynchronous job. While it is queued or running, the
    instance status reads not_found -- that is not a failure. Follow the job
    as the console does, until it succeeded or failed."""
    last = ""
    while True:
        try:
            j = api(cfg, "GET", resolve(cfg, job_url))
        except (ApiError, OSError) as exc:  # transient; keep polling
            j = {"status": "unknown", "message": str(exc)}
        st = j.get("status")
        text = {"running": "准备实例中", "queued": "排队等待 GPU 资源",
                "pending": "排队等待 GPU 资源"}.get(st, j.get("message", ""))
        line = f"  启动任务 {st}  {text}"
        if line != last:
            log(line)
            last = line
        if st == "succeeded":
            return
        if st == "failed":
            raise RuntimeError(f"启动任务失败：{j.get('message')} {j.get('error_code') or ''}")
        if time.time() > deadline:
            raise RuntimeError(f"等待 {cfg.ready_timeout:.0f} 秒后启动任务仍未完成（可能在排队等资源）")
        time.sleep(5)


def wait_ready(cfg: Config, job_url: str | None = None) -> dict:
    deadline = time.time() + cfg.ready_timeout
    if job_url:
        wait_job(cfg, job_url, deadline)
    last = ""
    missing = 0
    while True:
        try:
            s = status(cfg)
        except (ApiError, OSError) as exc:  # transient; keep polling
            s = {"status": "unknown", "message": str(exc)}
        ssh_stage = s.get("ssh_stage")
        line = f"  {s.get('status')}  {s.get('message', '')}" \
            + (f"  SSH 阶段：{ssh_stage}" if ssh_stage else "")
        if line != last:
            log(line)
            last = line
        # sshd is installed and started alongside the notebook: "ready" comes
        # first, ssh_stage settles later. The console keeps polling for it.
        if s.get("ready") and ssh_stage in (None, "", "ready", "failed"):
            if ssh_stage == "failed":
                log("⚠ 平台报告 SSH 启动失败")
            return s
        if s.get("status") == "failed":
            raise RuntimeError(f"实例启动失败：{s.get('message')} {s.get('reason') or ''}")
        # Past the launch job, a steady not_found means the instance is gone
        # (destroyed from the console, say). Without a job to follow, allow a
        # longer grace in case the launch is still being admitted.
        missing = missing + 1 if s.get("status") == "not_found" else 0
        if missing >= (6 if job_url else 24):
            raise RuntimeError("平台持续找不到实例（启动被取消，或实例已在控制台销毁）")
        if time.time() > deadline:
            raise RuntimeError(f"等待 {cfg.ready_timeout:.0f} 秒后实例仍未就绪")
        time.sleep(5)


def wait_ssh(cfg: Config, user: str, host: str, port) -> bool:
    """The platform reports ready once the container runs; sshd inside comes
    up later -- often minutes later. Until it does, connections are closed
    during key exchange. Poll with a real login."""
    deadline = time.time() + cfg.ssh_timeout
    cmd = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
           *cfg.ssh_opts.split(), f"{user}@{host}", "true"]
    log("  等待实例内的 SSH 服务就绪……")
    t0 = time.time()
    while time.time() < deadline:
        if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            log(f"  SSH 可以登录（平台就绪后又等了 {time.time() - t0:.0f} 秒）")
            return True
        time.sleep(10)
    return False


# The platform gives the notebook's main process an egress proxy, the HF mirror
# and a PyPI mirror through environment variables. SSH sessions do not inherit
# them, so without this every download from an SSH shell fails: DNS does not
# resolve public names and direct connections are blocked.
PLATFORM_ENV_SCRIPT = r"""
import shlex
keep = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY",
        "PIP_INDEX_URL")
lines = []
for kv in open("/proc/1/environ", "rb").read().split(b"\0"):
    k, _, v = kv.decode(errors="replace").partition("=")
    if k in keep or k.startswith("HF_"):
        lines.append(f"export {k}={shlex.quote(v)}")
lines.append('[ -d /opt/venv/bin ] && export PATH=/opt/venv/bin:$PATH')
open("/root/.platform_env", "w").write("\n".join(lines) + "\n")
print(len(lines))
"""


def write_platform_env(cfg: Config, user: str, host: str, port) -> None:
    cmd = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", *cfg.ssh_opts.split(),
           f"{user}@{host}", "python3", "-"]
    r = subprocess.run(cmd, input=PLATFORM_ENV_SCRIPT, capture_output=True, text=True)
    if r.returncode == 0:
        log("  已把平台的代理和镜像设置写入实例的 /root/.platform_env")
    else:
        log(f"⚠ 写入 /root/.platform_env 失败：{r.stderr.strip()[-200:]}")


def start_watchdog(cfg: Config, instance_id: str, minutes: float) -> tuple[int, float]:
    deadline = time.time() + minutes * 60
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_watchdog", instance_id, str(deadline)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)   # survives Ctrl-C and the parent shell exiting
    return proc.pid, deadline


def launch_body(cfg: Config) -> dict:
    """What the console sends: a template that pins a resource pool and
    resource template launches with an empty body -- adding gpu_count gets
    "400 Template uses an unsupported launch option". Older templates take
    gpu_count."""
    try:
        tpl = next((t for t in api(cfg, "GET", "/api/profile/templates").get("templates", [])
                    if str(t.get("id")) == str(cfg.template_id)), None)
    except ApiError:
        tpl = None
    if tpl is None:
        sys.exit(f"✗ 找不到模板 {cfg.template_id}（./cloud.py templates 查看）")
    if not tpl.get("launchable", True):
        sys.exit(f"✗ 模板 {cfg.template_id} 当前不能启动：{tpl.get('launchability_reason')}")
    if tpl.get("pod_type") and tpl.get("resource_template"):
        return {}
    return {"gpu_count": cfg.gpu_count}


def cmd_up(cfg: Config, args) -> dict:
    cfg.need_key()
    job_url = None
    s = status(cfg)
    state = read_state()
    if s.get("instance_id") and s.get("status") not in ("not_found", "failed"):
        ours = (state.get("instance_id") == s["instance_id"] and state.get("launched_by_us")) \
            or getattr(args, "own", False)
        log(f"✓ 已有实例 {s['instance_id']}（{s.get('status')}），直接使用"
            + ("，按本脚本启动的实例管理（看门狗、结束时销毁）" if ours and args.own else "")
            + ("" if ours else "；它不是本脚本启动的，session 结束时不会销毁（--own 可接管）"))
        launched = bool(ours)
        if launched and state.get("instance_id") != s["instance_id"]:
            clear_state()   # adopted a new instance: new host key, new watchdog
    else:
        if not cfg.template_id:
            sys.exit("✗ 没有模板：在 remote.env 中设置 RC_TEMPLATE_ID（./cloud.py templates 可查看 id）")
        body = launch_body(cfg)
        log(f"启动实例：模板 {cfg.template_id}，"
            + (f"{cfg.gpu_count} 张 GPU" if body else "资源规格由模板决定"))
        try:
            r = api(cfg, "POST", f"/api/templates/{cfg.template_id}/launch", body)
        except ApiError as exc:
            if exc.code in ("email_verification_required", "launch_verification_required"):
                sys.exit("✗ 平台要求先通过邮箱验证才能启动（需要验证码和人机验证，脚本无法完成）。\n"
                         "  请在控制台网页上启动实例，就绪后运行 ./cloud.py up --own（或 session --own），\n"
                         "  由脚本接管：启动看门狗，结束时自动销毁")
            hint = f"，{exc.retry_after} 秒后再试（启动次数有限制：约每分钟 1 次、每小时 5 次）" \
                if exc.status == 429 else ""
            sys.exit(f"✗ 启动失败：{exc}{hint}")
        launched = True
        job_url = r.get("status_url") if isinstance(r, dict) else None
        log(f"  已提交：{r.get('status') if isinstance(r, dict) else r}"
            + (f"，跟踪启动任务 {job_url}" if job_url else ""))
        clear_state()   # fresh instance: new host key, new watchdog
        write_state({"instance_id": None, "launched_by_us": True, "started": time.time()})

    try:
        s = wait_ready(cfg, job_url)
    except (RuntimeError, KeyboardInterrupt) as exc:
        if launched:
            log(f"✗ {str(exc) or '被中断'}；销毁实例，避免空跑计费")
            destroy(cfg)
            clear_state()
        raise SystemExit(1)

    state = read_state()
    state.update({
        "instance_id": s.get("instance_id"),
        "launched_by_us": launched,
        "started": state.get("started") or time.time(),
        "ssh_host": s.get("ssh_host"), "ssh_port": s.get("ssh_port"),
        "ssh_user": s.get("ssh_username") or "root",
    })
    minutes = args.max_minutes if args.max_minutes is not None else cfg.max_minutes
    if launched and minutes > 0 and not alive(state.get("watchdog_pid")):
        state["watchdog_pid"], state["deadline"] = start_watchdog(cfg, s["instance_id"], minutes)
        log(f"✓ 看门狗已启动：{minutes:g} 分钟后无论如何都会销毁实例（./cloud.py down 可提前销毁）")
    write_state(state)

    if not s.get("ssh_host"):
        log("⚠ 平台没有返回 SSH 地址：模板需要打开 SSH Access，账号需要设置 SSH 公钥")
    elif not wait_ssh(cfg, state["ssh_user"], s["ssh_host"], s["ssh_port"]):
        log(f"⚠ 等了 {cfg.ssh_timeout:.0f} 秒 SSH 仍无法登录（RC_SSH_TIMEOUT 可调大）。"
            "实例仍在运行，看门狗照常生效；不用时请 ./cloud.py down")
        state["ssh_ok"] = False
    else:
        write_platform_env(cfg, state["ssh_user"], s["ssh_host"], s["ssh_port"])
        log(f"✓ 实例就绪       {s['instance_id']}  "
            f"ssh {state['ssh_user']}@{s['ssh_host']} -p {s['ssh_port']}")
    return state


def cmd_down(cfg: Config, _args) -> int:
    cfg.need_key()
    r = destroy(cfg)
    clear_state()
    if r.get("success"):
        log(f"✓ 实例已销毁（{r.get('destroyed_count', 1)} 个），停止计费")
    else:
        log(f"没有正在运行的实例（{r.get('message', '')}）")
    return 0


def cmd_watchdog(cfg: Config, args) -> int:
    """Detached: sleep until the deadline, then destroy -- if it is still our instance."""
    instance_id, deadline = args.instance_id, float(args.deadline)
    while time.time() < deadline:
        time.sleep(min(60, max(1, deadline - time.time())))
        if read_state().get("instance_id") not in (instance_id, None):
            return 0   # a newer instance took over; its own watchdog is in charge
    try:
        if status(cfg).get("instance_id") == instance_id:
            destroy(cfg)
    finally:
        if read_state().get("instance_id") == instance_id:
            for path in (STATE, KNOWN_HOSTS):
                try:
                    os.remove(path)
                except OSError:
                    pass
    return 0


def cmd_session(cfg: Config, args) -> int:
    if not args.command:
        sys.exit("✗ 用法：./cloud.py session [--max-minutes N] -- <命令...>")
    state = cmd_up(cfg, args)
    owned = state.get("launched_by_us")
    rc = 1
    try:
        if state.get("ssh_ok") is False:
            raise RuntimeError("SSH 不可用")
        for step in (["remote_vllm.sh", "start"], ["tunnel.sh", "up"], ["remote_vllm.sh", "wait"]):
            subprocess.run([os.path.join(HERE, step[0]), *step[1:]], check=True)
        log(f"✓ 环境就绪，开始运行：{' '.join(args.command)}")
        rc = subprocess.run(args.command).returncode
        log(f"命令结束，返回码 {rc}")
    except subprocess.CalledProcessError as exc:
        log(f"✗ 准备步骤失败：{' '.join(exc.cmd)}")
    except KeyboardInterrupt:
        log("✗ 被中断")
    except RuntimeError as exc:
        log(f"✗ {exc}")
    finally:
        subprocess.run([os.path.join(HERE, "tunnel.sh"), "down"])
        if owned:
            cmd_down(cfg, args)
        else:
            log("⚠ 实例不是本脚本启动的，没有销毁；不用时请运行 ./cloud.py down")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="启动、查看、销毁 AMD Radeon Cloud GPU 实例")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("me", help="账号信息和余额")
    sub.add_parser("templates", help="列出模板和可用镜像")
    sub.add_parser("status", help="实例状态")
    sub.add_parser("down", help="销毁实例")
    for name in ("up", "session"):
        p = sub.add_parser(name, help="启动实例并等待就绪" if name == "up"
                           else "启动实例 → 运行命令 → 销毁实例")
        p.add_argument("--own", action="store_true",
                       help="已有实例（例如在控制台启动的）也按本脚本启动的实例管理："
                            "启动看门狗，session 结束时销毁")
        p.add_argument("--max-minutes", type=float, default=None,
                       help="看门狗时限（分钟），到时销毁实例；0 表示不启动看门狗。"
                            "默认取 remote.env 的 RC_MAX_MINUTES，未设置时为 180")
        if name == "session":
            p.add_argument("command", nargs=argparse.REMAINDER)
    w = sub.add_parser("_watchdog")
    w.add_argument("instance_id")
    w.add_argument("deadline")
    args = ap.parse_args()
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]

    # SIGTERM (from `timeout`, a CI runner, kill) must take the same path as
    # Ctrl-C, so the cleanup that destroys the instance runs -- also while
    # `up` is still waiting for it to become ready.
    def on_term(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, on_term)

    cfg = Config()
    try:
        if args.cmd == "up":
            cmd_up(cfg, args)
            return 0
        return {"me": cmd_me, "templates": cmd_templates, "status": cmd_status,
                "down": cmd_down, "session": cmd_session,
                "_watchdog": cmd_watchdog}[args.cmd](cfg, args)
    except ApiError as exc:
        hint = {401: "（凭据无效或已过期。中国站点的平台接口不接受 API key，"
                     "需要设置 RC_COOKIE，见 README）",
                403: "（账号未通过审核，或实例不属于你）"}
        sys.exit(f"✗ 平台接口出错：{exc}{hint.get(exc.status, '')}")
    except OSError as exc:
        sys.exit(f"✗ 连不上平台接口 {cfg.api_base}：{exc}")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
