
build:
	docker build --network host -t sshtunnel .

run:
	docker run -d --restart=always \
		-p 1080:1080 \
		-v `pwd`/ssh_keys:/ssh_keys:ro \
		--env-file ./my.env \
		wxyucs/sshtunnel:latest
