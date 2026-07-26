# Linux 原生方案

使用 Host 上的 OpenSSH 建立 SOCKS5 隧道，由用户级 systemd service 负责启动、
日志记录和断线重启，不需要 root 权限或 Docker。

## 安装

```sh
./install.sh
vi ~/.config/sshtunnel/config.env
systemctl --user restart sshtunnel
```

`SSH_IDENTITY_FILE` 可以留空，让 OpenSSH 搜索 `~/.ssh` 中的默认密钥。后台
服务启用了 `BatchMode=yes`，因此密钥必须无需交互式输入密码；如果使用加密
密钥，需要确保 systemd 用户服务能够访问已解锁的 `ssh-agent`。
首次运行前应手动连接一次 SSH 服务器，核对并写入 `known_hosts`：

```sh
ssh user@example.org
```

不经过 systemd、直接在前台验证命令行方案：

```sh
./run.sh
```

按 `Ctrl-C` 结束；确认连接正常后再启动 systemd 用户服务。

## 管理

```sh
systemctl --user status sshtunnel
systemctl --user restart sshtunnel
journalctl --user -u sshtunnel -f
make test
```

用户退出登录后仍需保持隧道时，可由管理员启用 linger：

```sh
sudo loginctl enable-linger "$USER"
```

卸载服务和 runner，但保留用户配置：

```sh
./uninstall.sh
```
