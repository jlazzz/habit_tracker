#!/bin/bash
# Browser checks for the page, run in Docker so nothing has to be installed on the host.
# Each script gets its own throwaway instance on 127.0.0.1:5001 with an empty database;
# the live container and its data are never touched. Screenshots land in tests/e2e/shots/.
#
#   tests/e2e/run.sh             # all three
#   tests/e2e/run.sh layout.py   # just one
cd "$(dirname "$0")/../.." || exit 1
PLAYWRIGHT=mcr.microsoft.com/playwright/python:v1.49.0-noble

docker build -q -t habit_tracker-e2e . >/dev/null || exit 1
mkdir -p tests/e2e/shots
status=0
for script in "${@:-core.py day.py layout.py}"; do
    for name in $script; do
        echo "== $name"
        data=$(mktemp -d)
        docker rm -f habit_e2e >/dev/null 2>&1
        docker run -d --name habit_e2e --user "$(id -u):$(id -g)" -p 127.0.0.1:5001:5000 -v "$data:/data" habit_tracker-e2e >/dev/null
        for _ in $(seq 1 50); do
            [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5001/)" = 200 ] && break
            python3 -c "import time; time.sleep(0.2)"
        done
        # Only failures and the summary are printed; drop the grep to see every check
        docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
            -v "$PWD/tests/e2e:/work:ro" -v "$PWD/tests/e2e/shots:/shots" "$PLAYWRIGHT" \
            bash -c "pip install -q --user playwright==1.49.0 >/dev/null 2>&1; python /work/$name http://127.0.0.1:5001" \
            | grep -v '^PASS'
        [ "${PIPESTATUS[0]}" = 0 ] || status=1
        docker rm -f habit_e2e >/dev/null 2>&1
        rm -rf "$data"
    done
done
exit $status
