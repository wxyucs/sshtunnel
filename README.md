# sshtunnel
A containerized auto-restart ssh tunnel.

## Usage

1. Clone this repository:
```shell
git clone https://github.com/wxyucs/sshtunnel.git
```

2. Put a identity file into the `ssh_keys` dir:
```shell
cp /path/to/identity_file ./ssh_keys/
```

3. Set the environment variables:
```shell
cp example.env my.env
vi my.env
```

4. Start the sshtunnel
```shell
make run
```
