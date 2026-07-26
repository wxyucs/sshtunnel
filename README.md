# sshtunnel

通过 SSH 动态端口转发提供本地代理，包含三种平行的部署方案。

| 方案 | 服务管理 | SOCKS5 | HTTP/HTTPS | 适合场景 |
| --- | --- | --- | --- | --- |
| [`container/`](container/) | Docker restart policy | `127.0.0.1:1080` | `127.0.0.1:1087` | 已使用 Docker、需要环境隔离 |
| [`macos/`](macos/) | detached CLI supervisor | 每个代理独立配置 | - | macOS 多代理后台运行与 Web 状态 |
| [`linux/`](linux/) | systemd user service | `127.0.0.1:1080` | - | Linux 长期后台运行 |

原生方案直接使用系统的 OpenSSH，并默认开启：

- `ExitOnForwardFailure=yes`
- `ServerAliveInterval=15`
- `ServerAliveCountMax=3`
- `BatchMode=yes`
- 严格的 SSH 主机密钥校验

## 快速选择

### Docker

```sh
cd container
cp example.env my.env
cp /path/to/private-key ssh_keys/id_rsa
make run
```

### macOS

```sh
cd macos
./install.sh
vi ~/.config/sshtunnel/config.json
sshtunnel start --web
```

### Linux

```sh
cd linux
./install.sh
vi ~/.config/sshtunnel/config.env
systemctl --user restart sshtunnel
```

各方案的安装、状态检查、日志和卸载方法见对应目录的 README。

## 设计文档

项目使用类似 Python Enhancement Proposal（PEP）的提案文档记录重要设计决策：

- [SEP 1：三种 SSH 隧道部署模式](docs/0001-three-deployment-modes.md)
- [SEP 2：macOS detached 多代理命令行生命周期](docs/0002-macos-detached-multi-proxy-cli.md)
- [SEP 3：macOS 代理状态 Web 接口](docs/0003-macos-status-web.md)
- [SEP 文档索引](docs/0000-index.md)
