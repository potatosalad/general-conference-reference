docker_image := "general-conference-reference"

[macos]
_docker-exec +args: docker-build
    docker run --rm --volume $(pwd):/project {{docker_image}} {{args}}

[macos]
_docker-interactive +args: docker-build
    docker run --rm --volume $(pwd):/project -it {{docker_image}} {{args}}

[group('docker')]
[macos]
docker-build:
    docker build -f ./Dockerfile -t {{docker_image}} .

[group('docker')]
[macos]
docker-execute:
    @just _docker-exec just execute

[group('docker')]
[macos]
docker-format:
    @just _docker-exec just format

[group('docker')]
[macos]
docker-lock:
    @just _docker-exec just uv-lock

[group('docker')]
[macos]
docker-shell:
    @just _docker-interactive /bin/bash
