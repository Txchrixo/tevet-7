#!/bin/bash
# start-backend.sh — démarre le backend Tevet-7 de façon PERSISTANTE.
#
# Utilise le double-fork daemon pattern (setsid + nohup + & + exit) pour
# reparenter le processus à init (PID 1). Les processus avec PPID=1
# survivent entre les appels Bash du sandbox.
#
# Le script vérifie que le backend répond avant de quitter.

set -e

LOG=/tmp/tevet7.log
PID_FILE=/tmp/tevet7.pid

# Si le backend est déjà up, ne rien faire.
if curl -s -m 2 -o /dev/null http://localhost:8001/health 2>/dev/null; then
    echo "[start-backend] already running (health=200)"
    exit 0
fi

echo "[start-backend] starting..."

# Double-fork daemon: setsid bash -c 'nohup cmd & echo $! > pidfile; exit 0'
# Le bash parent exits immédiatement, le nohup'd python est reparenté à init.
setsid bash -c "
    cd /home/z/my-project/agentic-service
    nohup /home/z/.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > $LOG 2>&1 < /dev/null &
    echo \$! > $PID_FILE
    exit 0
" < /dev/null > /dev/null 2>&1

# Attendre que le backend réponde (init_db + seed + ML = ~18-20s)
for i in $(seq 1 30); do
    sleep 2
    if curl -s -m 3 -o /dev/null http://localhost:8001/health 2>/dev/null; then
        echo "[start-backend] ready (health=200, pid=$(cat $PID_FILE 2>/dev/null), ppid=$(ps -o ppid= -p $(cat $PID_FILE 2>/dev/null) 2>/dev/null | tr -d ' '))"
        exit 0
    fi
done

echo "[start-backend] FAILED — backend didn't start in 60s"
tail -20 $LOG 2>/dev/null
exit 1
