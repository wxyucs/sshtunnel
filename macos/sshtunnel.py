#!/usr/bin/env python3
"""Detached multi-proxy SSH tunnel manager for macOS."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_CONFIG = Path("~/.config/sshtunnel/config.json").expanduser()
DEFAULT_STATE_DIR = Path("~/Library/Application Support/sshtunnel").expanduser()
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DETACHED_CHILDREN: List[subprocess.Popen[Any]] = []


class ConfigError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{field} must be between {minimum} and {maximum}")
    return value


def nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def load_config(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be an object")

    state_dir_value = raw.get("state_dir", str(DEFAULT_STATE_DIR))
    state_dir = expand_path(nonempty_string(state_dir_value, "state_dir"))

    web_raw = raw.get("web", {})
    if not isinstance(web_raw, dict):
        raise ConfigError("web must be an object")
    web = {
        "bind_host": nonempty_string(web_raw.get("bind_host", "127.0.0.1"), "web.bind_host"),
        "port": integer(web_raw.get("port", 8787), "web.port", 1, 65535),
    }

    proxies_raw = raw.get("proxies")
    if not isinstance(proxies_raw, list) or not proxies_raw:
        raise ConfigError("proxies must be a non-empty array")

    proxies: Dict[str, Dict[str, Any]] = {}
    endpoints: Dict[Tuple[str, int], str] = {}
    for index, item in enumerate(proxies_raw):
        prefix = f"proxies[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{prefix} must be an object")

        name = nonempty_string(item.get("name"), f"{prefix}.name")
        if not NAME_PATTERN.fullmatch(name):
            raise ConfigError(
                f"{prefix}.name must start with an alphanumeric character and contain only "
                "letters, digits, dot, underscore, or hyphen"
            )
        if name in proxies:
            raise ConfigError(f"duplicate proxy name: {name}")

        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{prefix}.enabled must be true or false")

        bind_host = nonempty_string(item.get("bind_host", "127.0.0.1"), f"{prefix}.bind_host")
        socks_port = integer(item.get("socks_port", 1080), f"{prefix}.socks_port", 1, 65535)
        endpoint = (bind_host, socks_port)
        if endpoint in endpoints:
            raise ConfigError(
                f"proxy {name} conflicts with {endpoints[endpoint]} on "
                f"{bind_host}:{socks_port}"
            )
        endpoints[endpoint] = name

        identity_value = item.get("identity_file", "")
        if not isinstance(identity_value, str):
            raise ConfigError(f"{prefix}.identity_file must be a string")

        extra_options = item.get("extra_options", [])
        if not isinstance(extra_options, list) or not all(
            isinstance(value, str) and value for value in extra_options
        ):
            raise ConfigError(f"{prefix}.extra_options must be an array of non-empty strings")

        proxies[name] = {
            "name": name,
            "enabled": enabled,
            "ssh_host": nonempty_string(item.get("ssh_host"), f"{prefix}.ssh_host"),
            "ssh_user": nonempty_string(item.get("ssh_user"), f"{prefix}.ssh_user"),
            "ssh_port": integer(item.get("ssh_port", 22), f"{prefix}.ssh_port", 1, 65535),
            "identity_file": str(expand_path(identity_value)) if identity_value else "",
            "bind_host": bind_host,
            "socks_port": socks_port,
            "server_alive_interval": integer(
                item.get("server_alive_interval", 15),
                f"{prefix}.server_alive_interval",
                1,
                3600,
            ),
            "server_alive_count_max": integer(
                item.get("server_alive_count_max", 3),
                f"{prefix}.server_alive_count_max",
                1,
                100,
            ),
            "restart_delay": integer(
                item.get("restart_delay", 5), f"{prefix}.restart_delay", 1, 3600
            ),
            "extra_options": extra_options,
        }

    web_endpoint = (web["bind_host"], web["port"])
    if web_endpoint in endpoints:
        raise ConfigError(
            f"web conflicts with proxy {endpoints[web_endpoint]} on "
            f"{web['bind_host']}:{web['port']}"
        )

    return {
        "path": path.resolve(),
        "state_dir": state_dir,
        "web": web,
        "proxies": proxies,
    }


def ensure_runtime_dirs(config: Dict[str, Any]) -> None:
    state_dir: Path = config["state_dir"]
    for directory in (
        state_dir,
        state_dir / "proxies",
        state_dir / "locks",
        state_dir / "logs",
    ):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def proxy_state_path(config: Dict[str, Any], name: str) -> Path:
    return config["state_dir"] / "proxies" / f"{name}.json"


def proxy_log_path(config: Dict[str, Any], name: str) -> Path:
    return config["state_dir"] / "logs" / f"{name}.log"


def web_state_path(config: Dict[str, Any]) -> Path:
    return config["state_dir"] / "web.json"


def web_log_path(config: Dict[str, Any]) -> Path:
    return config["state_dir"] / "logs" / "web.log"


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


@contextlib.contextmanager
def named_lock(config: Dict[str, Any], name: str) -> Iterable[None]:
    lock_path = config["state_dir"] / "locks" / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def lease_path(config: Dict[str, Any], token: str) -> Path:
    return config["state_dir"] / "locks" / f"lease-{token}.lock"


def acquire_process_lease(
    config: Dict[str, Any], token: str
) -> Tuple[Any, Path]:
    path = lease_path(config, token)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lease_file = path.open("a+", encoding="utf-8")
    fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX)
    return lease_file, path


def release_process_lease(lease_file: Any, path: Path) -> None:
    fcntl.flock(lease_file.fileno(), fcntl.LOCK_UN)
    lease_file.close()
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def process_matches(config: Dict[str, Any], pid: Any, token: Any) -> bool:
    if not isinstance(pid, int) or pid <= 1 or not isinstance(token, str) or not token:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    path = lease_path(config, token)
    try:
        lease_file = path.open("r+", encoding="utf-8")
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lease_file.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        lease_file.close()


def proxy_status(config: Dict[str, Any], proxy: Dict[str, Any]) -> Dict[str, Any]:
    state = read_json(proxy_state_path(config, proxy["name"])) or {}
    running = process_matches(config, state.get("pid"), state.get("token"))
    phase = state.get("phase") if running else "stopped"
    return {
        "name": proxy["name"],
        "enabled": proxy["enabled"],
        "running": running,
        "phase": phase,
        "pid": state.get("pid") if running else None,
        "child_pid": state.get("child_pid") if running else None,
        "started_at": state.get("started_at") if running else None,
        "last_exit_code": state.get("last_exit_code"),
        "ssh_target": f"{proxy['ssh_user']}@{proxy['ssh_host']}:{proxy['ssh_port']}",
        "socks_endpoint": f"{proxy['bind_host']}:{proxy['socks_port']}",
        "log_file": str(proxy_log_path(config, proxy["name"])),
    }


def web_status(config: Dict[str, Any]) -> Dict[str, Any]:
    state = read_json(web_state_path(config)) or {}
    running = process_matches(config, state.get("pid"), state.get("token"))
    return {
        "running": running,
        "pid": state.get("pid") if running else None,
        "started_at": state.get("started_at") if running else None,
        "url": f"http://{config['web']['bind_host']}:{config['web']['port']}/",
        "log_file": str(web_log_path(config)),
    }


def select_proxies(
    config: Dict[str, Any], names: List[str], enabled_only: bool
) -> List[Dict[str, Any]]:
    if names:
        missing = [name for name in names if name not in config["proxies"]]
        if missing:
            raise ConfigError(f"unknown proxy: {', '.join(missing)}")
        return [config["proxies"][name] for name in names]
    proxies = list(config["proxies"].values())
    return [proxy for proxy in proxies if proxy["enabled"]] if enabled_only else proxies


def internal_command(config: Dict[str, Any], command: str, *arguments: str) -> List[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--config",
        str(config["path"]),
        command,
        *arguments,
    ]


def wait_for(
    predicate: Any, timeout: float, interval: float = 0.1
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def start_proxy(config: Dict[str, Any], proxy: Dict[str, Any]) -> Tuple[bool, str]:
    ensure_runtime_dirs(config)
    name = proxy["name"]
    with named_lock(config, f"proxy-{name}"):
        current = proxy_status(config, proxy)
        if current["running"]:
            return True, f"{name}: already {current['phase']} (pid {current['pid']})"

        with contextlib.suppress(FileNotFoundError):
            proxy_state_path(config, name).unlink()

        token = uuid.uuid4().hex
        log_path = proxy_log_path(config, name)
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                internal_command(config, "_supervise", name, token),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        _DETACHED_CHILDREN.append(process)

        started = wait_for(
            lambda: proxy_status(config, proxy)["running"] or process.poll() is not None,
            timeout=5,
        )
        status = proxy_status(config, proxy)
        if started and status["running"]:
            return True, f"{name}: started ({status['phase']}, pid {status['pid']})"
        return False, f"{name}: failed to start; see {log_path}"


def terminate_detached(
    config: Dict[str, Any],
    pid: int,
    token: str,
    child_pid: Optional[int] = None,
    timeout: float = 10,
) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    exited = wait_for(
        lambda: not process_matches(config, pid, token), timeout=timeout
    )
    if not exited:
        if isinstance(child_pid, int) and child_pid > 1:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(child_pid, signal.SIGTERM)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        wait_for(lambda: not process_matches(config, pid, token), timeout=2)


def stop_proxy(config: Dict[str, Any], proxy: Dict[str, Any]) -> Tuple[bool, str]:
    ensure_runtime_dirs(config)
    name = proxy["name"]
    with named_lock(config, f"proxy-{name}"):
        state_path = proxy_state_path(config, name)
        state = read_json(state_path) or {}
        if not process_matches(config, state.get("pid"), state.get("token")):
            with contextlib.suppress(FileNotFoundError):
                state_path.unlink()
            return True, f"{name}: already stopped"

        pid = state["pid"]
        token = state["token"]
        terminate_detached(config, pid, token, state.get("child_pid"))
        with contextlib.suppress(FileNotFoundError):
            state_path.unlink()
        if process_matches(config, pid, token):
            return False, f"{name}: could not stop pid {pid}"
        return True, f"{name}: stopped"


def build_ssh_command(proxy: Dict[str, Any]) -> List[str]:
    ssh_binary = os.environ.get("SSHTUNNEL_SSH_BIN", "/usr/bin/ssh")
    command = [
        ssh_binary,
        "-N",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        f"ServerAliveInterval={proxy['server_alive_interval']}",
        "-o",
        f"ServerAliveCountMax={proxy['server_alive_count_max']}",
        "-p",
        str(proxy["ssh_port"]),
        "-D",
        f"{proxy['bind_host']}:{proxy['socks_port']}",
    ]
    if proxy["identity_file"]:
        command.extend(["-i", proxy["identity_file"]])
    command.extend(proxy["extra_options"])
    command.append(f"{proxy['ssh_user']}@{proxy['ssh_host']}")
    return command


def supervise(config: Dict[str, Any], name: str, token: str) -> int:
    proxy = config["proxies"].get(name)
    if proxy is None:
        print(f"sshtunnel: unknown proxy: {name}", file=sys.stderr, flush=True)
        return 2

    identity_file = proxy["identity_file"]
    if identity_file and (
        not Path(identity_file).is_file() or not os.access(identity_file, os.R_OK)
    ):
        print(f"sshtunnel: identity file is not readable: {identity_file}", file=sys.stderr)
        return 2

    state_path = proxy_state_path(config, name)
    started_at = now_iso()
    stop_event = threading.Event()
    child: Optional[subprocess.Popen[Any]] = None

    def handle_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()
        if child is not None and child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                child.terminate()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    base_state: Dict[str, Any] = {
        "name": name,
        "pid": os.getpid(),
        "token": token,
        "started_at": started_at,
    }
    command = build_ssh_command(proxy)
    last_exit_code: Optional[int] = None
    lease_file, held_lease_path = acquire_process_lease(config, token)

    try:
        while not stop_event.is_set():
            write_json(
                state_path,
                {
                    **base_state,
                    "phase": "starting",
                    "child_pid": None,
                    "last_exit_code": last_exit_code,
                },
            )
            try:
                child = subprocess.Popen(command)
            except OSError as exc:
                print(f"{now_iso()} failed to execute SSH: {exc}", file=sys.stderr, flush=True)
                write_json(
                    state_path,
                    {
                        **base_state,
                        "phase": "restarting",
                        "child_pid": None,
                        "last_exit_code": last_exit_code,
                        "error": str(exc),
                    },
                )
                stop_event.wait(proxy["restart_delay"])
                continue

            write_json(
                state_path,
                {
                    **base_state,
                    "phase": "running",
                    "child_pid": child.pid,
                    "command_started_at": now_iso(),
                    "last_exit_code": last_exit_code,
                },
            )
            exit_code = child.wait()
            last_exit_code = exit_code
            child = None
            if stop_event.is_set():
                break

            print(
                f"{now_iso()} SSH exited with {exit_code}; restarting in "
                f"{proxy['restart_delay']} seconds",
                file=sys.stderr,
                flush=True,
            )
            write_json(
                state_path,
                {
                    **base_state,
                    "phase": "restarting",
                    "child_pid": None,
                    "last_exit_code": exit_code,
                },
            )
            stop_event.wait(proxy["restart_delay"])
    finally:
        if child is not None and child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                child.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=3)
        state = read_json(state_path) or {}
        if state.get("token") == token:
            with contextlib.suppress(FileNotFoundError):
                state_path.unlink()
        release_process_lease(lease_file, held_lease_path)
    return 0


def status_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "proxies": [
            proxy_status(config, proxy) for proxy in config["proxies"].values()
        ],
        "web": web_status(config),
    }


def render_status_html(config: Dict[str, Any]) -> str:
    payload = status_payload(config)
    rows = []
    for proxy in payload["proxies"]:
        css_class = "running" if proxy["running"] else "stopped"
        rows.append(
            "<tr>"
            f"<td>{html.escape(proxy['name'])}</td>"
            f"<td>{'yes' if proxy['enabled'] else 'no'}</td>"
            f"<td><span class=\"badge {css_class}\">{html.escape(proxy['phase'])}</span></td>"
            f"<td>{html.escape(proxy['socks_endpoint'])}</td>"
            f"<td>{html.escape(proxy['ssh_target'])}</td>"
            f"<td>{proxy['pid'] or '-'}</td>"
            f"<td>{proxy['child_pid'] or '-'}</td>"
            f"<td>{proxy['last_exit_code'] if proxy['last_exit_code'] is not None else '-'}</td>"
            f"<td>{html.escape(proxy['started_at'] or '-')}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="5">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>sshtunnel status</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem;
            color: #17202a; background: #f7f9fb; }}
    main {{ max-width: 1100px; margin: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: white;
             box-shadow: 0 1px 4px #ccd2d8; }}
    th, td {{ padding: .75rem; border-bottom: 1px solid #e6e9ec; text-align: left; }}
    .badge {{ border-radius: 999px; padding: .2rem .6rem; font-weight: 600; }}
    .running {{ color: #126b3a; background: #dff5e8; }}
    .stopped {{ color: #8a2631; background: #fde5e8; }}
    code {{ background: #edf0f2; padding: .15rem .35rem; border-radius: 4px; }}
  </style>
</head>
<body>
<main>
  <h1>SSH 代理状态</h1>
  <p>每 5 秒刷新。JSON API：<code>/api/status</code></p>
  <table>
    <thead><tr><th>名称</th><th>启用</th><th>状态</th><th>SOCKS5</th><th>SSH 目标</th><th>Supervisor PID</th><th>SSH PID</th><th>最近退出码</th><th>启动时间</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p>更新时间：{html.escape(payload['generated_at'])}</p>
</main>
</body>
</html>
"""


def make_handler(config_path: Path) -> Any:
    class StatusHandler(BaseHTTPRequestHandler):
        server_version = "sshtunnel-status/1"

        def do_GET(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            try:
                current_config = load_config(config_path)
                if path == "/":
                    body = render_status_html(current_config).encode("utf-8")
                    self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
                elif path == "/api/status":
                    body = json.dumps(
                        status_payload(current_config),
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8")
                    self._send(HTTPStatus.OK, "application/json; charset=utf-8", body)
                elif path == "/healthz":
                    self._send(HTTPStatus.OK, "text/plain; charset=utf-8", b"ok\n")
                else:
                    self._send(
                        HTTPStatus.NOT_FOUND,
                        "application/json; charset=utf-8",
                        b'{"error":"not found"}\n',
                    )
            except ConfigError as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "application/json; charset=utf-8",
                    body,
                )

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, message_format: str, *arguments: Any) -> None:
            print(
                f"{now_iso()} {self.client_address[0]} "
                f"{message_format % arguments}",
                file=sys.stderr,
                flush=True,
            )

    return StatusHandler


def serve_web(config: Dict[str, Any], token: str) -> int:
    ensure_runtime_dirs(config)
    host = config["web"]["bind_host"]
    port = config["web"]["port"]
    state_path = web_state_path(config)
    server = ThreadingHTTPServer((host, port), make_handler(config["path"]))
    server.daemon_threads = True
    lease_file, held_lease_path = acquire_process_lease(config, token)

    def handle_stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    write_json(
        state_path,
        {
            "pid": os.getpid(),
            "token": token,
            "started_at": now_iso(),
            "bind_host": host,
            "port": port,
        },
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        state = read_json(state_path) or {}
        if state.get("token") == token:
            with contextlib.suppress(FileNotFoundError):
                state_path.unlink()
        release_process_lease(lease_file, held_lease_path)
    return 0


def start_web(config: Dict[str, Any]) -> Tuple[bool, str]:
    ensure_runtime_dirs(config)
    with named_lock(config, "web"):
        current = web_status(config)
        if current["running"]:
            return True, f"web: already running at {current['url']} (pid {current['pid']})"

        with contextlib.suppress(FileNotFoundError):
            web_state_path(config).unlink()
        token = uuid.uuid4().hex
        log_path = web_log_path(config)
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                internal_command(config, "_serve-web", token),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        _DETACHED_CHILDREN.append(process)
        started = wait_for(
            lambda: web_status(config)["running"] or process.poll() is not None,
            timeout=5,
        )
        status = web_status(config)
        if started and status["running"]:
            return True, f"web: started at {status['url']} (pid {status['pid']})"
        return False, f"web: failed to start; see {log_path}"


def stop_web(config: Dict[str, Any]) -> Tuple[bool, str]:
    ensure_runtime_dirs(config)
    with named_lock(config, "web"):
        state_path = web_state_path(config)
        state = read_json(state_path) or {}
        if not process_matches(config, state.get("pid"), state.get("token")):
            with contextlib.suppress(FileNotFoundError):
                state_path.unlink()
            return True, "web: already stopped"
        pid = state["pid"]
        token = state["token"]
        terminate_detached(config, pid, token)
        with contextlib.suppress(FileNotFoundError):
            state_path.unlink()
        if process_matches(config, pid, token):
            return False, f"web: could not stop pid {pid}"
        return True, "web: stopped"


def print_proxy_statuses(statuses: List[Dict[str, Any]]) -> None:
    print(f"{'NAME':<20} {'STATUS':<12} {'SOCKS5':<24} {'PID':<8} SSH TARGET")
    for status in statuses:
        pid = str(status["pid"]) if status["pid"] else "-"
        print(
            f"{status['name']:<20} {status['phase']:<12} "
            f"{status['socks_endpoint']:<24} {pid:<8} {status['ssh_target']}"
        )


def command_start(config: Dict[str, Any], names: List[str], with_web: bool) -> int:
    proxies = select_proxies(config, names, enabled_only=True)
    results = [start_proxy(config, proxy) for proxy in proxies]
    if with_web:
        results.append(start_web(config))
    for _success, message in results:
        print(message)
    return 0 if all(success for success, _message in results) else 1


def command_stop(config: Dict[str, Any], names: List[str], with_web: bool) -> int:
    if names:
        invalid = [name for name in names if not NAME_PATTERN.fullmatch(name)]
        if invalid:
            raise ConfigError(f"invalid proxy name: {', '.join(invalid)}")
        unknown = [
            name
            for name in names
            if name not in config["proxies"]
            and not proxy_state_path(config, name).exists()
        ]
        if unknown:
            raise ConfigError(f"unknown proxy: {', '.join(unknown)}")
        stop_names = names
    else:
        runtime_names = {
            path.stem
            for path in (config["state_dir"] / "proxies").glob("*.json")
            if NAME_PATTERN.fullmatch(path.stem)
        }
        stop_names = list(config["proxies"]) + sorted(
            runtime_names.difference(config["proxies"])
        )
    proxies = [{"name": name} for name in stop_names]
    results = [stop_proxy(config, proxy) for proxy in proxies]
    if with_web:
        results.append(stop_web(config))
    for _success, message in results:
        print(message)
    return 0 if all(success for success, _message in results) else 1


def command_restart(config: Dict[str, Any], names: List[str], with_web: bool) -> int:
    proxies = select_proxies(config, names, enabled_only=True)
    results: List[Tuple[bool, str]] = []
    for proxy in proxies:
        results.append(stop_proxy(config, proxy))
        results.append(start_proxy(config, proxy))
    if with_web:
        results.append(stop_web(config))
        results.append(start_web(config))
    for _success, message in results:
        print(message)
    return 0 if all(success for success, _message in results) else 1


def command_status(config: Dict[str, Any], names: List[str], as_json: bool) -> int:
    proxies = select_proxies(config, names, enabled_only=False)
    statuses = [proxy_status(config, proxy) for proxy in proxies]
    if as_json:
        print(json.dumps({"generated_at": now_iso(), "proxies": statuses}, indent=2))
    else:
        print_proxy_statuses(statuses)
    return 0


def command_web(config: Dict[str, Any], action: str, as_json: bool) -> int:
    if action == "start":
        success, message = start_web(config)
    elif action == "stop":
        success, message = stop_web(config)
    elif action == "restart":
        stop_web(config)
        success, message = start_web(config)
    else:
        status = web_status(config)
        if as_json:
            print(json.dumps(status, indent=2))
        else:
            state = "running" if status["running"] else "stopped"
            pid = f" (pid {status['pid']})" if status["pid"] else ""
            print(f"web: {state}{pid}; {status['url']}")
        return 0 if status["running"] else 1
    print(message)
    return 0 if success else 1


def command_logs(config: Dict[str, Any], name: str, lines: int, follow: bool) -> int:
    if not NAME_PATTERN.fullmatch(name):
        raise ConfigError(f"invalid proxy name: {name}")
    log_path = proxy_log_path(config, name)
    if name not in config["proxies"] and not log_path.exists():
        raise ConfigError(f"unknown proxy: {name}")
    if not log_path.exists():
        print(f"sshtunnel: log does not exist yet: {log_path}", file=sys.stderr)
        return 1
    command = ["/usr/bin/tail", "-n", str(lines)]
    if follow:
        command.append("-f")
    command.append(str(log_path))
    return subprocess.call(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sshtunnel")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("SSHTUNNEL_CONFIG", DEFAULT_CONFIG)),
        help=f"configuration path (default: {DEFAULT_CONFIG})",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{start,stop,restart,status,logs,web}",
    )

    for command in ("start", "stop", "restart"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("names", nargs="*", help="proxy names; defaults to all")
        subparser.add_argument("--web", action="store_true", help="manage web status too")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("names", nargs="*", help="proxy names; defaults to all")
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("name")
    logs_parser.add_argument("-n", "--lines", type=int, default=50)
    logs_parser.add_argument("-f", "--follow", action="store_true")

    web_parser = subparsers.add_parser("web")
    web_parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    web_parser.add_argument("--json", action="store_true", dest="as_json")

    supervise_parser = subparsers.add_parser("_supervise", help=argparse.SUPPRESS)
    supervise_parser.add_argument("name")
    supervise_parser.add_argument("token")

    serve_parser = subparsers.add_parser("_serve-web", help=argparse.SUPPRESS)
    serve_parser.add_argument("token")
    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if action.dest not in {"_supervise", "_serve-web"}
    ]
    return parser


def main(arguments: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        config = load_config(args.config.expanduser())
        if args.command == "start":
            return command_start(config, args.names, args.web)
        if args.command == "stop":
            return command_stop(config, args.names, args.web)
        if args.command == "restart":
            return command_restart(config, args.names, args.web)
        if args.command == "status":
            return command_status(config, args.names, args.as_json)
        if args.command == "logs":
            return command_logs(config, args.name, args.lines, args.follow)
        if args.command == "web":
            return command_web(config, args.action, args.as_json)
        if args.command == "_supervise":
            return supervise(config, args.name, args.token)
        if args.command == "_serve-web":
            return serve_web(config, args.token)
    except (ConfigError, OSError) as exc:
        print(f"sshtunnel: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
