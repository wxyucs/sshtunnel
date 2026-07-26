```text
SEP: 2
Title: macOS detached 多代理命令行生命周期
Author: wxyucs
Status: Final
Type: Standards Track
Created: 2026-07-26
Requires: SEP 1
Replaces: SEP 1 macOS lifecycle
```

# 摘要

本提案用一个基于 Python 标准库的命令行工具取代 macOS launchd agent。
CLI 以类似 `nohup` 的 detached 方式管理一个或多个 SSH SOCKS5 代理。每个代理
拥有独立 supervisor、SSH 子进程、状态文件和日志，可以批量或按名称操作。

# 动机

launchd 适合登录后自动启动的系统集成，但增加了 plist 安装、domain 加载和
KeepAlive 语义。当前需求更接近用户显式执行命令后在后台持续运行，并希望：

- 不安装或依赖 launchd。
- 使用一个 CLI 启动、停止、重启和检查状态。
- 在一个配置文件内声明多个互不影响的代理。
- SSH 断开时只重启对应代理。
- 终端退出后后台任务继续运行。

# 规范

## 运行依赖

参考实现面向 macOS，需要：

- Python 3.9 或更新版本。
- `/usr/bin/ssh`，或测试时通过 `SSHTUNNEL_SSH_BIN` 指定的兼容程序。
- Python 标准库；不得要求 pip 安装第三方包。

## 配置文件

默认配置路径为：

```text
~/.config/sshtunnel/config.json
```

顶层字段：

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `state_dir` | 否 | `~/Library/Application Support/sshtunnel` | 状态、锁和日志根目录 |
| `web` | 否 | 本地 `8787` | SEP 3 定义的 Web 配置 |
| `proxies` | 是 | 无 | 非空代理数组 |

每个代理支持：

| 字段 | 必填 | 默认值 |
| --- | --- | --- |
| `name` | 是 | 无 |
| `enabled` | 否 | `true` |
| `ssh_host` | 是 | 无 |
| `ssh_user` | 是 | 无 |
| `ssh_port` | 否 | `22` |
| `identity_file` | 否 | 空 |
| `bind_host` | 否 | `127.0.0.1` |
| `socks_port` | 否 | `1080` |
| `server_alive_interval` | 否 | `15` |
| `server_alive_count_max` | 否 | `3` |
| `restart_delay` | 否 | `5` |
| `extra_options` | 否 | `[]` |

代理名称必须唯一，只允许字母、数字、点、下划线和连字符，且必须以字母或数字
开始。本地 `bind_host` 与 `socks_port` 组合也必须唯一，防止多个 supervisor
争用同一端口。

`ssh_host` 可以是 DNS 主机名、IP 地址或 OpenSSH config 中的别名。路径字段必须
展开 `~` 和环境变量。

## CLI

公开命令：

```text
sshtunnel start [name ...] [--web]
sshtunnel stop [name ...] [--web]
sshtunnel restart [name ...] [--web]
sshtunnel status [name ...] [--json]
sshtunnel logs <name> [-n lines] [-f]
sshtunnel web <start|stop|restart|status> [--json]
```

未指定名称时：

- `start` 和 `restart` 选择全部 `enabled=true` 的代理。
- `stop` 和 `status` 选择配置中的全部代理。
- 显式名称可以操作 `enabled=false` 的代理。

批量操作必须逐个执行并报告每个代理结果。一个代理失败不得阻止其他代理被操作；
只要任意操作失败，CLI 最终退出码必须非零。

## Detached supervisor

每个代理由单独的 supervisor 进程管理。CLI 启动 supervisor 时必须：

- 将标准输入连接到 `/dev/null`。
- 将标准输出和错误输出追加到该代理日志。
- 创建新的 session，使其不依赖调用终端。
- 等待 supervisor 写入有效状态，确认启动成功后再返回。

supervisor 启动的 SSH 命令必须包含：

```text
-N
-T
-o BatchMode=yes
-o ExitOnForwardFailure=yes
-o ServerAliveInterval=<configured value>
-o ServerAliveCountMax=<configured value>
```

SSH 意外退出后，supervisor 只等待该代理的 `restart_delay`，然后重启该 SSH
子进程。其他代理和 Web 服务不受影响。

## 状态与进程身份

每个代理状态文件为：

```text
<state_dir>/proxies/<name>.json
```

至少包含 supervisor PID、随机 token、当前阶段、启动时间和 SSH 子进程 PID。
CLI 判断进程身份时必须同时验证 PID 存在且进程命令行包含对应 token，不能只依赖
PID 文件。停止操作先向 supervisor 发送 `SIGTERM`，由 supervisor 转发给 SSH；
超时后才允许分别清理子进程和 supervisor。

每个代理必须使用独立 advisory lock，避免同名代理的并发启停竞态。

无名称的 `stop` 必须同时扫描状态目录，清理已经从配置中删除但仍在运行的代理。
显式名称也允许停止存在状态文件的已删除代理。由于状态目录是发现后台进程的
边界，修改 `state_dir` 前必须先停止全部代理和 Web 服务。

# 安全考虑

- SOCKS5 默认只监听 `127.0.0.1`。
- 保留 OpenSSH 默认主机密钥校验，不允许默认设置
  `StrictHostKeyChecking=no`。
- `BatchMode=yes` 禁止后台密码提示；加密密钥需要已解锁且后台进程可访问的
  SSH agent。
- 配置文件由安装器以 `0600` 创建。
- 状态目录和状态文件分别使用用户私有目录和 `0600` 文件权限。
- `extra_options` 是受信任配置，可能改变 SSH 安全行为，操作者需要自行审核。

# 向后兼容性和迁移

本提案仅替换 macOS 方案；Container 和 Linux 不变。

安装器必须停止并删除旧 `com.wxyucs.sshtunnel` launchd agent 和旧 runner，
避免两套实现争用 `1080`。旧 `config.env` 不自动执行或删除；安装器提示用户将其
手工迁移到 `config.json`。

# 被拒绝的方案

## 直接执行 `nohup ssh ... &`

它满足终端退出后继续运行，但没有可靠的多代理状态、PID 身份验证、独立重启、
结构化配置和统一日志命令。

## 保留 launchd 作为隐藏实现

这不符合明确的不使用 launchd 要求，也会继续暴露 launchctl domain 和 plist
生命周期。

## 一个 supervisor 管理全部代理

单进程实现更容易集中管理，但 supervisor 故障会同时影响所有代理，不满足代理
相互独立的要求。

# 参考实现

参考实现为：

- `macos/sshtunnel.py`
- `macos/config.example.json`
- `macos/install.sh`
- `macos/uninstall.sh`
- `macos/tests/test_sshtunnel.py`

自动化测试必须验证 CLI 进程退出后 supervisor 仍然运行，以及多个代理可以独立
启动和停止。
