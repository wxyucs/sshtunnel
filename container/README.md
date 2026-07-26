# Container 方案

容器内的 OpenSSH 在 `1080` 提供 SOCKS5，Privoxy 将 `1087` 的 HTTP/HTTPS
代理请求转发到 SOCKS5。两个端口默认仅映射到 Host 的 `127.0.0.1`。

## 配置与启动

```sh
cp example.env my.env
cp /path/to/private-key ssh_keys/id_rsa
chmod 600 ssh_keys/id_rsa
vi my.env
make run
```

使用本地源码构建和运行：

```sh
make build
make test
```

## 验证

```sh
curl --proxy socks5h://127.0.0.1:1080 https://ifconfig.me
curl --proxy http://127.0.0.1:1087 https://ifconfig.me
```

查看日志或删除容器：

```sh
make logs
make stop
```

为了兼容原项目，容器方案仍设置了 `StrictHostKeyChecking=no`，不会校验 SSH
服务器身份。需要更高安全性时，应挂载专用 `known_hosts`，并在
`entrypoint.sh` 中改用 `StrictHostKeyChecking=yes` 和 `UserKnownHostsFile`。
