.PHONY: install uninstall start stop restart status logs test

LABEL := com.wxyucs.sshtunnel
DOMAIN := gui/$(shell id -u)
PLIST := $(HOME)/Library/LaunchAgents/$(LABEL).plist

install:
	./install.sh

uninstall:
	./uninstall.sh

start:
	@launchctl print $(DOMAIN)/$(LABEL) >/dev/null 2>&1 || launchctl bootstrap $(DOMAIN) $(PLIST)
	launchctl kickstart $(DOMAIN)/$(LABEL)

stop:
	launchctl bootout $(DOMAIN)/$(LABEL)

restart:
	@launchctl print $(DOMAIN)/$(LABEL) >/dev/null 2>&1 || launchctl bootstrap $(DOMAIN) $(PLIST)
	launchctl kickstart -k $(DOMAIN)/$(LABEL)

status:
	launchctl print $(DOMAIN)/$(LABEL)

logs:
	log stream --style compact --predicate 'process == "ssh"'

test:
	curl --fail --show-error --proxy socks5h://127.0.0.1:1080 https://ifconfig.me
