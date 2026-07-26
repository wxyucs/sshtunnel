.PHONY: help build test run stop logs macos-install macos-uninstall linux-install linux-uninstall

help:
	@echo "Container: make build | test | run | stop | logs"
	@echo "macOS:    make macos-install | macos-uninstall"
	@echo "Linux:    make linux-install | linux-uninstall"

# Backward-compatible container targets.
build test run stop logs:
	$(MAKE) -C container $@

macos-install:
	./macos/install.sh

macos-uninstall:
	./macos/uninstall.sh

linux-install:
	./linux/install.sh

linux-uninstall:
	./linux/uninstall.sh
