FROM alpine:latest
RUN apk add openssh
RUN apk add privoxy
RUN echo "forward-socks5 / 127.0.0.1 ." >> /etc/privoxy/config
RUN echo "listen-address 0.0.0.0:1087" >> /etc/privoxy/config

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["sh", "/entrypoint.sh"]
