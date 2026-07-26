# macOS 原生方案

使用系统自带的 `/usr/bin/ssh` 建立 SOCKS5 隧道，由用户级 `launchd` agent
负责登录后启动和断线重启，不需要 Docker。

## 安装

```sh
./install.sh
vi ~/.config/sshtunnel/config.env
make restart
```

`SSH_IDENTITY_FILE` 可以留空，让 OpenSSH 搜索 `~/.ssh` 中的默认密钥。后台
服务启用了 `BatchMode=yes`，因此密钥必须无需交互式输入密码；如果使用加密
密钥，需要确保 launchd 服务能够访问已解锁的 `ssh-agent`。
首次运行前应手动连接一次 SSH 服务器，核对并写入 `known_hosts`：

```sh
ssh user@example.org
```

不经过 launchd、直接在前台验证命令行方案：

```sh
./run.sh
```

按 `Ctrl-C` 结束；确认连接正常后再使用 `make restart` 交给 launchd 管理。

## 管理

```sh
make status
make restart
make stop
make start
make test
```

查看 SSH 进程的统一日志：

```sh
make logs
```

卸载服务和 runner，但保留用户配置：

```sh
./uninstall.sh
```
