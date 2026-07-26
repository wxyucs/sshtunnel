# macOS 多代理命令行方案

该方案不使用 launchd。`sshtunnel` CLI 以类似 `nohup` 的方式启动独立后台
supervisor：标准输入断开、日志写入文件、创建新 session，因此终端退出后仍会
运行。每个代理有自己的 supervisor、PID 状态和日志；一个代理退出或重启不会
影响其他代理。

运行要求：macOS、系统 OpenSSH、Python 3.9 或更新版本。Python 实现只使用标准
库。

## 安装

```sh
cd macos
./install.sh
vi ~/.config/sshtunnel/config.json
```

安装器将 CLI 复制到 `~/.local/bin/sshtunnel`。如果 shell 找不到命令，将
`~/.local/bin` 加入 `PATH`，或者使用完整路径。

旧版 launchd agent 会在安装时停止并移除；旧的 `config.env` 会保留，需手工
将其值迁移到 `config.json`。

## 配置

完整示例见 [`config.example.json`](config.example.json)：

```json
{
  "state_dir": "~/Library/Application Support/sshtunnel",
  "web": {
    "bind_host": "127.0.0.1",
    "port": 8787
  },
  "proxies": [
    {
      "name": "primary",
      "enabled": true,
      "ssh_host": "proxy.example.org",
      "ssh_user": "root",
      "ssh_port": 22,
      "identity_file": "~/.ssh/id_ed25519",
      "bind_host": "127.0.0.1",
      "socks_port": 1080,
      "server_alive_interval": 15,
      "server_alive_count_max": 3,
      "restart_delay": 5
    }
  ]
}
```

代理字段：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `name` | 必填 | 唯一代理名称，用于命令、状态文件和日志 |
| `enabled` | `true` | 无名称执行 `start` 时是否自动启动 |
| `ssh_host` | 必填 | SSH 主机名、IP 或 SSH config 中的别名 |
| `ssh_user` | 必填 | SSH 用户 |
| `ssh_port` | `22` | SSH 服务端口 |
| `identity_file` | 空 | 私钥路径；为空时由 OpenSSH 选择 |
| `bind_host` | `127.0.0.1` | 本地 SOCKS5 监听地址 |
| `socks_port` | `1080` | 本地 SOCKS5 端口 |
| `server_alive_interval` | `15` | SSH 存活探测间隔 |
| `server_alive_count_max` | `3` | 连续无响应次数 |
| `restart_delay` | `5` | SSH 退出后的重启等待秒数 |
| `extra_options` | `[]` | 额外 SSH 参数数组 |

所有代理的 `name` 和本地监听地址/端口组合必须唯一，Web 地址也不能与 SOCKS5
端口冲突。首次启动前先手动连接 SSH 服务器，核对并写入 `known_hosts`。后台
任务启用了 `BatchMode=yes`，不能处理交互式密码或主机密钥确认。

修改或删除代理配置前建议先执行 `sshtunnel stop`。如果代理已从配置中删除但
状态目录未改变，无名称的 `stop` 仍会扫描状态文件并清理它；修改 `state_dir`
前则必须先停止所有任务。

## 命令

没有指定代理名称时，`start`/`restart` 操作所有 `enabled` 代理，`stop` 和
`status` 操作配置中的所有代理：

```sh
# 一次启动全部 enabled 代理，并启动状态网页
sshtunnel start --web

# 只操作指定代理
sshtunnel start primary backup
sshtunnel restart primary
sshtunnel stop backup

# 查看文本或 JSON 状态
sshtunnel status
sshtunnel status primary --json

# 查看代理日志
sshtunnel logs primary
sshtunnel logs -f primary

# 停止所有代理和网页
sshtunnel stop --web
```

也可以使用其他配置文件：

```sh
sshtunnel --config /path/to/config.json start --web
```

## Web 状态

网页进程与代理 supervisor 相互独立：

```sh
sshtunnel web start
sshtunnel web status
open http://127.0.0.1:8787/
sshtunnel web stop
```

只读接口：

- `/`：每 5 秒刷新的状态页面。
- `/api/status`：JSON 状态。
- `/healthz`：健康检查。

Web 默认只监听 `127.0.0.1` 且没有认证。不要直接绑定公网地址；远程访问应通过
SSH 转发或带认证的反向代理。

## 文件位置

```text
~/.config/sshtunnel/config.json
~/Library/Application Support/sshtunnel/
├── proxies/<name>.json
├── locks/
├── logs/<name>.log
├── logs/web.log
└── web.json
```

状态文件包含随机 token，CLI 在发送信号前同时验证 PID 和 token，降低 PID
复用导致误杀其他进程的风险。

## 验证与卸载

```sh
curl --proxy socks5h://127.0.0.1:1080 https://ifconfig.me
make test
./uninstall.sh
```

卸载器先停止代理和 Web 服务，再删除 CLI；配置、状态目录和日志会保留。
