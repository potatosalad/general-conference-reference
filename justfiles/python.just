[linux]
setup-python:
    # Use the latest available pip
    pip install --upgrade pip
    # Use the latest available uv
    pip install --upgrade uv

[linux]
[working-directory: '/project']
uv-lock:
    uv lock
    uv sync
    (uv export --format requirements.txt --no-hashes --no-annotate | awk '{ print $1 }' FS=';' | awk '{$1=$1};1') > requirements.txt

[linux]
[working-directory: '/project']
uv-sync:
    uv sync
