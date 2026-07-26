FROM alpine:latest

RUN apk add --no-cache openssh privoxy \
    && echo "forward-socks5 / 127.0.0.1 ." >> /etc/privoxy/config \
    && echo "listen-address 0.0.0.0:1087" >> /etc/privoxy/config

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["sh", "/entrypoint.sh"]
