#!/bin/bash
# start-bridge.sh — démarre le GLM bridge de façon persistante.
set -e
if curl -s -m 2 -o /dev/null http://localhost:3030/health 2>/dev/null; then
    echo "[start-bridge] already running"
    exit 0
fi
echo "[start-bridge] starting..."
setsid bash -c "
    cd /home/z/my-project/mini-services/glm-bridge
    nohup bun run dev > /tmp/glm-bridge.log 2>&1 < /dev/null &
    echo \$! > /tmp/glm-bridge.pid
    exit 0
" < /dev/null > /dev/null 2>&1
sleep 4
if curl -s -m 3 -o /dev/null http://localhost:3030/health 2>/dev/null; then
    echo "[start-bridge] ready"
    exit 0
fi
echo "[start-bridge] FAILED"
exit 1
