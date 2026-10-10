#!/usr/bin/env bash
# Smoke-test disposable containers without secrets, cloud APIs or a database.
set -euo pipefail
backend_image=${1:-cloudscope-backend:test}
web_image=${2:-cloudscope-web:test}
network="cloudscope-image-test-$$"
backend="${network}-api"
web="${network}-web"
cleanup() {
  docker rm -f "$web" "$backend" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$backend" --network "$network" --network-alias cloudscope-api "$backend_image" >/dev/null
docker run -d --name "$web" --network "$network" --network-alias cloudscope-web "$web_image" >/dev/null
for container in "$backend" "$web"; do
  test "$(docker exec "$container" id -u)" != 0
done
docker run --rm "$backend_image" collect --help >/dev/null
docker run --rm --entrypoint alembic "$backend_image" heads | grep -q '(head)'
docker exec -i "$backend" python - <<'PY'
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get(url):
    for _ in range(30):
        try:
            with urlopen(url, timeout=2) as response:
                return response.status, response.read(), response.headers
        except HTTPError as response:
            return response.code, response.read(), response.headers
        except URLError:
            time.sleep(1)
    raise AssertionError(f"Container did not become available: {url}")


status, body, _ = get('http://localhost:8000/healthz')
assert status == 200 and json.loads(body) == {'status': 'ok'}
status, body, headers = get('http://cloudscope-web:8080/login')
assert status == 200 and b'<div id="root">' in body
assert headers['Cache-Control'] == 'no-cache'
status, body, _ = get('http://cloudscope-web:8080/api/auth/me')
assert status == 503 and json.loads(body) == {'detail': 'Authentication unavailable'}
assert get('http://cloudscope-web:8080/assets/missing.js')[0] == 404
print('Non-root images, CLI, migrations, API health, SPA fallback and API proxy passed.')
PY
