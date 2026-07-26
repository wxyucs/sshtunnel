.PHONY: install uninstall start stop restart status web-start web-stop web-status logs test

CLI ?= $(HOME)/.local/bin/sshtunnel
PROXY ?= primary

install:
	./install.sh

uninstall:
	./uninstall.sh

start:
	$(CLI) start --web

stop:
	$(CLI) stop --web

restart:
	$(CLI) restart --web

status:
	$(CLI) status

web-start:
	$(CLI) web start

web-stop:
	$(CLI) web stop

web-status:
	$(CLI) web status

logs:
	$(CLI) logs -f $(PROXY)

test:
	python3 -m unittest discover -s tests -v
