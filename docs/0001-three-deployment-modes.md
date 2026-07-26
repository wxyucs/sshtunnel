```text
SEP: 1
Title: 三种 SSH 隧道部署模式
Author: wxyucs
Status: Final
Type: Standards Track
Created: 2026-07-26
Superseded-By: SEP 2 (macOS lifecycle), SEP 3 (macOS status interface)
```

# 摘要

本提案将项目从单一 Docker 实现调整为三个平行、可独立使用的部署方案：

- Container：Docker 管理 OpenSSH 和 Privoxy。
- macOS：系统 OpenSSH 配合用户级 launchd agent。
- Linux：系统 OpenSSH 配合 systemd user service。

三种方案都提供 SSH 动态端口转发。原生方案只提供 SOCKS5；Container 方案额外
通过 Privoxy 提供 HTTP/HTTPS 代理。

SEP 2 和 SEP 3 已取代本文的 macOS 生命周期与状态管理部分。Container 和
Linux 规范不受影响。

# 动机

原项目只有容器化实现。它容易复制，也能打包 Privoxy，但固定依赖 Docker，
需要把私钥挂载进容器，并增加端口映射和容器网络的排障层级。

在固定 Host 上长期运行时，直接使用系统 OpenSSH 可以复用 `~/.ssh`、
`known_hosts` 和操作系统的进程管理能力。macOS 和 Linux 的可靠后台运行机制
不同：前者使用 launchd，后者通常使用 systemd。因此原生实现不应被包装成一个
假定两种平台生命周期完全一致的通用脚本。

# 规范

## 目录结构

仓库顶层必须保留三个平行方案：

```text
container/
macos/
linux/
```

每个目录必须包含独立 README 和操作入口。根 Makefile 保留旧的
`build`、`test`、`run`、`stop`、`logs` 命令，并将其转发到 Container 方案，
避免已有调用立即失效。

## Container 方案

Container 方案必须：

- 在容器内监听 SOCKS5 `0.0.0.0:1080`。
- 使用 Privoxy 在容器内监听 `0.0.0.0:1087`。
- 默认只把两个端口映射到 Host 的 `127.0.0.1`。
- 使用 Docker restart policy 处理 SSH 进程退出。
- 将 SSH 作为容器主进程运行，并使用 `-N -T`。
- 在 GitHub Actions 中使用 `container/` 作为镜像构建上下文。

为了保持原部署兼容性，Container 方案暂时保留
`StrictHostKeyChecking=no`。这是明确记录的安全债务，不代表原生方案的默认
行为。需要验证服务器身份的部署应挂载专用 `known_hosts`，并改为严格校验。

## 原生方案的共同配置

macOS 和 Linux 使用同一组配置字段，默认路径为：

```text
~/.config/sshtunnel/config.env
```

字段定义如下：

| 字段 | 必填 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `SSH_HOST` | 是 | 无 | SSH 服务器主机名或地址 |
| `SSH_USER` | 是 | 无 | SSH 登录用户 |
| `SSH_IDENTITY_FILE` | 否 | 空 | 显式指定的私钥；为空时由 OpenSSH 搜索默认身份 |
| `SSH_PORT` | 否 | `22` | SSH 服务器端口 |
| `SOCKS_BIND_ADDRESS` | 否 | `127.0.0.1` | 本地 SOCKS5 监听地址 |
| `SOCKS_PORT` | 否 | `1080` | 本地 SOCKS5 端口 |
| `SERVER_ALIVE_INTERVAL` | 否 | `15` | SSH 存活探测间隔，单位为秒 |
| `SERVER_ALIVE_COUNT_MAX` | 否 | `3` | 连续无响应阈值 |

原生 runner 必须使用：

```text
-N
-T
-o BatchMode=yes
-o ExitOnForwardFailure=yes
-o ServerAliveInterval=<configured value>
-o ServerAliveCountMax=<configured value>
```

原生方案不得默认关闭 SSH 主机密钥校验，也不得默认监听
`0.0.0.0`。配置缺少必填字段、端口字段不是整数或显式私钥不可读时，runner
必须在调用 SSH 前失败并输出可理解的错误。

## macOS 生命周期

> 本节已被 SEP 2 和 SEP 3 取代，仅保留为历史设计记录。

macOS 方案使用用户级 launchd agent：

```text
~/Library/LaunchAgents/com.wxyucs.sshtunnel.plist
```

runner 安装到：

```text
~/.local/libexec/sshtunnel/run
```

launchd 必须在异常退出或网络状态变化后重新拉起隧道。`stop` 操作必须卸载
agent，而不是只向 SSH 进程发送信号，否则 KeepAlive 会立刻重启进程。

首次安装生成空配置时不得立即加载 agent。用户填写配置后，`start` 或
`restart` 命令负责加载并启动它。

## Linux 生命周期

Linux 方案使用 systemd user service：

```text
~/.config/systemd/user/sshtunnel.service
```

runner 安装到：

```text
~/.local/libexec/sshtunnel/run
```

服务使用 `Restart=always` 和固定的重启间隔。首次安装生成空配置时只启用
服务，不立即启动；已有配置时允许安装脚本直接启用并启动。

默认情况下，用户服务可能在用户退出后停止。确需无人登录时持续运行的部署，
由管理员显式执行 `loginctl enable-linger <user>`，项目不得在安装脚本中自动
扩大这一生命周期权限。

## 日志和验证

- Container 方案通过 `docker logs` 查看日志。
- macOS 方案通过统一日志查看 SSH 进程信息。
- Linux 方案通过 `journalctl --user -u sshtunnel` 查看日志。
- 三种方案都必须提供通过 SOCKS5 请求外部地址的验证示例。
- 原生 runner 必须支持不经过服务管理器直接在前台运行，以便先验证 SSH、
  私钥、`known_hosts` 和端口占用。

# 安全考虑

代理端口默认只监听 Host 的 `127.0.0.1`，避免意外成为局域网或公网开放代理。
如需向其他设备提供服务，操作者必须显式修改监听地址，并自行配置防火墙和访问
控制。

配置文件会被 shell 读取，因此它属于当前用户控制的受信任配置，不应复制不可信
内容。安装脚本以 `0600` 创建配置文件。

后台服务启用 `BatchMode=yes`，不会弹出密码或主机密钥确认。使用加密私钥时，
操作者必须确保服务能够访问已经解锁的 SSH agent；否则应使用权限受限的专用
服务密钥。

# 向后兼容性

以下行为保持兼容：

- 根目录 `make build`、`make test` 和 `make run` 仍操作 Container 方案。
- Docker Hub 镜像名称仍为 `wxyucs/sshtunnel`。
- Container 内部端口仍为 `1080` 和 `1087`。
- Container 环境字段仍为 `IDENTITY_FILE`、`USER` 和 `HOST`。

仓库内部文件路径由根目录迁移到 `container/`。直接引用根目录 Dockerfile、
`entrypoint.sh` 或 `example.env` 的外部自动化必须更新路径。

# 被拒绝的方案

## 继续只维护 Docker 方案

该方案无法满足不依赖 Docker 的 Host 原生运行需求。

## 用一个跨平台后台脚本统一 macOS 和 Linux

SSH 命令可以共享，但 launchd 与 systemd 在安装路径、启停语义、日志和用户
会话生命周期上不同。强行统一会隐藏关键平台差异，增加排障成本。

## 使用 `nohup` 或 `ssh -f` 作为正式后台机制

它们缺少明确的服务状态、可靠重启和统一日志，不适合作为长期运行规范。

## 强制依赖 autossh

OpenSSH 的存活探测配合 launchd/systemd 重启已覆盖当前故障模型。增加 autossh
会引入额外依赖和第二层重启逻辑；如未来出现现有机制无法处理的实际故障，可由
新 SEP 重新评估。

# 参考实现

本提案的参考实现位于：

- `container/`
- `macos/`
- `linux/`

根 README 是用户入口，本 SEP 是设计和兼容性规范。实现发生行为变化时，应先
更新本提案或提交新的 SEP。
