"""演示控制命令仅在 API 主机通过 Unix 套接字传递。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path, PureWindowsPath
import socket
import socketserver
import stat
import struct
import sys
import tempfile
import threading


_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_READ_FILE = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
_SOCKET = "control.sock"
_COMMANDS = {"ui": ("on", "off", "status"), "mode": ("submission", "local")}
_USAGE = "用法：run_api.sh ui on|off|status 或 run_api.sh mode submission|local"


@contextmanager
def _directory(path: Path, parts: tuple[str, ...] = ()) -> Iterator[int]:
    """逐层打开，后续操作锚定在已核验的目录描述符上。"""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("目录需要使用绝对路径")
    fd = os.open("/", _DIRECTORY)
    try:
        for part in (*path.parts[1:], *parts):
            next_fd = os.open(part, _DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _owned_private(info: os.stat_result) -> bool:
    return info.st_uid == os.geteuid() and (info.st_mode & 0o077) == 0


def _read_file(directory: int, name: str, *, limit: int = -1, private: bool = False) -> bytes:
    fd = os.open(name, _READ_FILE, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (private and not _owned_private(info)):
            raise ValueError("文件类型或权限无效")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(limit)
    finally:
        os.close(fd)


def _valid_id(task_id: str) -> bool:
    if task_id == ".":
        return True  # 题库根目录也可以直接放一道题。
    return (isinstance(task_id, str) and not PureWindowsPath(task_id).drive
            and "\\" not in task_id and "\0" not in task_id
            and all(part not in ("", ".", "..") for part in task_id.split("/")))


class TaskCatalog:
    """按相对目录名索引公开题面。目录和文件均不跟随符号链接。"""

    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None
        if self.root is not None and (not self.root.is_absolute() or ".." in self.root.parts):
            raise ValueError("本地题库需要使用绝对目录")

    def list(self) -> list[str]:
        if self.root is None:
            return []
        tasks = []
        try:
            with _directory(self.root) as root:
                for path, directories, files, directory in os.fwalk(".", dir_fd=root):
                    relative = Path(path)
                    directories[:] = [
                        name for name in directories if _valid_id((relative / name).as_posix())
                    ]
                    if "prompt.txt" in files:
                        info = os.stat("prompt.txt", dir_fd=directory, follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode):
                            tasks.append(relative.as_posix())
        except OSError as exc:
            raise ValueError("无法读取本地题库") from exc
        return sorted(tasks)

    def prompt(self, task_id: str) -> str:
        if self.root is None or not _valid_id(task_id):
            raise ValueError("本地题目编号无效")
        parts = () if task_id == "." else tuple(task_id.split("/"))
        try:
            with _directory(self.root, parts) as directory:
                return _read_file(directory, "prompt.txt").decode("utf-8")
        except (OSError, ValueError) as exc:
            raise ValueError("本地题目不存在或无法读取 UTF-8 题面") from exc


@contextmanager
def _runtime_directory(*, create: bool) -> Iterator[int]:
    scratch = Path(os.environ.get("AGENT_TMP") or "/var/tmp").absolute()
    port = os.environ.get("API_PORT") or "7860"
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("API_PORT 无效")
    name = f".rtlagent-ui-{os.geteuid()}-{int(port)}"
    with _directory(scratch) as parent:
        info = os.fstat(parent)
        shared_writable = info.st_mode & 0o022
        if info.st_uid not in (0, os.geteuid()) or (shared_writable and not info.st_mode & stat.S_ISVTX):
            raise ValueError("AGENT_TMP 需由当前用户或 root 持有，共享可写目录须带 sticky 位")
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open(name, _DIRECTORY, dir_fd=parent)
        try:
            if not _owned_private(os.fstat(fd)):
                raise ValueError("控制目录须为当前用户私有")
            yield fd
        finally:
            os.close(fd)


def _saved_mode(directory: int) -> str:
    try:
        data = _read_file(directory, "mode", limit=32, private=True)
    except FileNotFoundError:
        return "submission"
    for mode in _COMMANDS["mode"]:
        if data == (mode + "\n").encode("ascii"):
            return mode
    raise ValueError("已保存的投题模式无效")


def persist_mode(mode: str) -> None:
    """由服务在同一把作业锁内调用，文件替换成功后再切换内存状态。"""
    if mode not in _COMMANDS["mode"]:
        raise ValueError("投题模式无效")
    with _runtime_directory(create=False) as directory:
        with tempfile.NamedTemporaryFile(dir=f"/proc/self/fd/{directory}", delete=False) as draft:
            name = os.path.basename(draft.name)
            try:
                draft.write((mode + "\n").encode("ascii"))
                draft.flush()
                os.fsync(draft.fileno())
                os.replace(name, "mode", src_dir_fd=directory, dst_dir_fd=directory)
            finally:
                try:
                    os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass


def _socket_path(directory: int) -> str:
    # Linux 根据目录项查找本机套接字。描述符路径也适用于超过 sun_path 上限的 AGENT_TMP。
    return f"/proc/self/fd/{directory}/{_SOCKET}"


def _check_peer(connection: socket.socket) -> None:
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", credentials)
    if uid != os.geteuid():
        raise PermissionError("控制端仅接受同一用户")


def _command(args: list[str]) -> tuple[str, str]:
    if len(args) != 2 or args[1] not in _COMMANDS.get(args[0], ()):
        raise ValueError(_USAGE)
    return args[0], args[1]


class _Request(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(2)
        try:
            _check_peer(self.connection)
            line = self.rfile.readline(64)
            if not line.endswith(b"\n"):
                raise ValueError(_USAGE)
            command, value = _command(line[:-1].decode("ascii").split(" "))
            response = self.server.control(command, value)
            body = json.dumps(response, ensure_ascii=True, allow_nan=False)
        except (ValueError, PermissionError, TimeoutError):
            body = json.dumps({"error": "控制命令无效或无法执行"})
        except Exception:
            body = json.dumps({"error": "控制命令执行失败"})
        try:
            self.wfile.write(body.encode("ascii") + b"\n")
        except OSError:
            pass  # 客户端退出时，已经完成的命令保留其结果。


@contextmanager
def local_control(handler: Callable[[str, str | None], dict]) -> Iterator[None]:
    """API lifespan 在接受 HTTP 请求前恢复模式，并持有唯一的本机控制端。"""
    with _runtime_directory(create=True) as directory:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("此 API 已有活动的控制进程") from exc
        restored = handler("restore", _saved_mode(directory))
        if "error" in restored:
            raise RuntimeError("无法恢复已保存的投题模式")
        try:
            old = os.stat(_SOCKET, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(old.st_mode) or old.st_uid != os.geteuid():
                raise ValueError("控制套接字的类型或所有者无效")
            os.unlink(_SOCKET, dir_fd=directory)  # 上一进程异常退出，目录锁已释放。
        with socketserver.UnixStreamServer(_socket_path(directory), _Request) as server:
            try:
                os.chmod(_SOCKET, 0o600, dir_fd=directory)
                server.control = handler
                worker = threading.Thread(target=server.serve_forever,
                                          kwargs={"poll_interval": 0.1}, daemon=True)
                worker.start()
                try:
                    yield
                finally:
                    server.shutdown()
                    worker.join()
            finally:
                os.unlink(_SOCKET, dir_fd=directory)


def _send(command: str, value: str) -> dict:
    with _runtime_directory(create=False) as directory, socket.socket(socket.AF_UNIX) as connection:
        info = os.stat(_SOCKET, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode) or not _owned_private(info):
            raise ValueError("控制套接字的类型或权限无效")
        connection.settimeout(5)
        connection.connect(_socket_path(directory))
        _check_peer(connection)
        connection.sendall(f"{command} {value}\n".encode("ascii"))
        with connection.makefile("rb") as stream:
            line = stream.readline(65536)
        if not line.endswith(b"\n"):
            raise ValueError("控制服务返回不完整")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise ValueError("控制服务回复无效")
        return response


def main(args: list[str]) -> int:
    try:
        command, value = _command(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        reply = _send(command, value)
    except OSError:
        print("无法连接本机 API 控制服务，请核对服务状态、AGENT_TMP 和 API_PORT", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    failed = "error" in reply
    print(json.dumps(reply, ensure_ascii=False), file=sys.stderr if failed else sys.stdout)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
