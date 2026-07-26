```text
SEP: 3
Title: macOS 代理状态 Web 接口
Author: wxyucs
Status: Final
Type: Standards Track
Created: 2026-07-26
Requires: SEP 2
Replaces: SEP 1 macOS status interface
```

# 摘要

本提案为 SEP 2 的 macOS 多代理 CLI 增加独立、只读的 HTTP 状态服务，提供浏览器
页面、JSON API 和健康检查。Web 服务不能控制代理，也不能成为代理 supervisor
的共同故障点。

# 动机

命令行状态适合本机运维，但多个代理同时运行时，浏览器表格更容易快速查看代理
名称、运行阶段、本地端口、SSH 目标和 PID。结构化 JSON 也便于后续菜单栏工具、
监控或自动化集成。

# 规范

## 生命周期

Web 状态服务由以下命令独立管理：

```text
sshtunnel web start
sshtunnel web stop
sshtunnel web restart
sshtunnel web status [--json]
```

`sshtunnel start --web`、`stop --web` 和 `restart --web` 是同时操作代理与 Web
服务的便捷入口，不改变两者独立运行的事实。

Web 服务使用与代理 supervisor 相同的 detached 机制，但有独立 PID、随机 token、
状态文件、锁和日志：

```text
<state_dir>/web.json
<state_dir>/locks/web.lock
<state_dir>/logs/web.log
```

Web 服务异常退出后不自动重启。用户可以通过 `web status` 发现并显式重启；后续
若需要 Web 自恢复，应通过新 SEP 定义，不能重新引入 launchd。

## 配置

```json
{
  "web": {
    "bind_host": "127.0.0.1",
    "port": 8787
  }
}
```

`bind_host` 默认为 `127.0.0.1`，`port` 必须为 `1` 至 `65535` 的整数，且不得
与任一 SOCKS5 监听地址和端口组合冲突。

HTTP server 绑定本地地址时不得执行 FQDN 或反向 DNS 查询；状态服务不依赖主机名，
而这类查询可能在离线网络或 CI runner 上无限延迟启动。

## HTTP 接口

服务必须提供：

| 路径 | Content-Type | 说明 |
| --- | --- | --- |
| `/` | `text/html; charset=utf-8` | 状态表格，默认每 5 秒刷新 |
| `/api/status` | `application/json` | 结构化代理和 Web 状态 |
| `/healthz` | `text/plain` | 服务健康检查，成功返回 `200` 和 `ok` |

其他路径返回 `404`。配置在请求时重新读取，因此增删代理后无需重启 Web 服务即可
看到新配置；代理进程本身仍需通过 SEP 2 的 `restart` 应用 SSH 参数变化。

页面和 API 至少展示：

- 代理名称和 `enabled` 状态。
- supervisor 是否运行以及当前阶段。
- 本地 SOCKS5 地址。
- SSH 用户、主机和端口。
- supervisor PID、SSH 子进程 PID和启动时间。
- 最近一次 SSH 退出码（如有）。

接口不得返回私钥路径、随机 token、完整 SSH 命令或环境变量。

# 安全考虑

Web 接口当前不提供认证或 TLS，且暴露 SSH 目标和本地运行信息，因此必须默认只
监听 `127.0.0.1`。项目文档不得建议将它直接绑定公网地址。

需要远程查看时，应使用 SSH 本地端口转发，或置于具备认证与 TLS 的反向代理
之后。HTTP 服务只实现 GET，不提供启动、停止或修改代理的接口，避免浏览器请求
改变后台状态。

所有 HTML 中的配置和状态字符串必须转义，JSON 必须通过标准序列化器生成。
响应设置 `Cache-Control: no-store`。

# 被拒绝的方案

## 在浏览器中提供启停按钮

这需要认证、CSRF 防护和更严格的权限模型。当前目标是查看状态，控制操作继续由
本机 CLI 承担。

## 为每个代理运行一个 Web 服务

这会浪费端口和进程。只读聚合服务不会控制代理，因此单个 Web 服务失败不影响
代理独立性。

## 生成静态 HTML 文件

静态文件需要轮询刷新任务，容易显示过期 PID。按请求读取状态文件可以保持实现
简单并返回实时信息。

# 测试要求

自动化测试必须至少覆盖：

- Web 服务能够 detached 启停。
- `/api/status` 返回配置中的代理且反映运行状态。
- `/` 返回包含代理名称的 HTML。
- 多代理测试中停止一个代理不会改变另一个代理的运行状态。

# 参考实现

参考实现位于 `macos/sshtunnel.py`，测试位于
`macos/tests/test_sshtunnel.py`。
