
build:
	docker build --network host -t sshtunnel .

test:
	docker run -d --restart=always \
		--name=sshtunnel-test \
		-p 1080:1080 \
		-p 1087:1087 \
		-v `pwd`/ssh_keys:/ssh_keys:ro \
		--env-file ./my.env \
		sshtunnel:latest

run:
	docker run -d --restart=always \
		--name=sshtunnel \
		-p 1080:1080 \
		-p 1087:1087 \
		-v `pwd`/ssh_keys:/ssh_keys:ro \
		--env-file ./my.env \
		wxyucs/sshtunnel:latest
