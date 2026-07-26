.PHONY: install uninstall start stop restart status logs test

install:
	./install.sh

uninstall:
	./uninstall.sh

start:
	systemctl --user start sshtunnel

stop:
	systemctl --user stop sshtunnel

restart:
	systemctl --user restart sshtunnel

status:
	systemctl --user status sshtunnel

logs:
	journalctl --user -u sshtunnel -f

test:
	curl --fail --show-error --proxy socks5h://127.0.0.1:1080 https://ifconfig.me
