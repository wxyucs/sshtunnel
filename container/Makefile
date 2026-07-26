.PHONY: build test run stop logs

IMAGE ?= wxyucs/sshtunnel:latest
LOCAL_IMAGE ?= sshtunnel:latest

build:
	docker build -t $(LOCAL_IMAGE) .

test:
	docker run -d --restart=always \
		--name=sshtunnel-test \
		-p 127.0.0.1:1080:1080 \
		-p 127.0.0.1:1087:1087 \
		-v "$(CURDIR)/ssh_keys:/ssh_keys:ro" \
		--env-file ./my.env \
		$(LOCAL_IMAGE)

run:
	docker run -d --restart=always \
		--name=sshtunnel \
		-p 127.0.0.1:1080:1080 \
		-p 127.0.0.1:1087:1087 \
		-v "$(CURDIR)/ssh_keys:/ssh_keys:ro" \
		--env-file ./my.env \
		$(IMAGE)

stop:
	docker rm -f sshtunnel

logs:
	docker logs -f sshtunnel
