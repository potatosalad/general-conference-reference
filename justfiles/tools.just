[linux]
[working-directory: '/project']
execute: uv-sync format
    uv run general_conference_reference /project

[macos]
execute: docker-execute

[linux]
format: format-python-src

[linux]
[working-directory: '/project']
format-python-src:
    uv run black /project/src/

[macos]
format: docker-format

[linux]
lock:
    just uv-lock

[macos]
lock: docker-lock

[macos]
shell: docker-shell

[macos]
watch:
    watchexec -w codegen -- just execute
