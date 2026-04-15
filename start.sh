#!/bin/bash

LOG_DIR="/bots/biddingbot/logs"
LOG_FILE="$LOG_DIR/app.log"

mkdir -p "$LOG_DIR"

handle_exit() {
    echo "Shutting down..." >> "$LOG_FILE"
    kill -TERM "$main_pid" 2>/dev/null
}

trap handle_exit TERM INT

echo "Starting app at $(date)" >> "$LOG_FILE"

source /bots/biddingbot/venv/bin/activate || echo "Failed to activate venv" >> "$LOG_FILE"

/bots/biddingbot/venv/bin/python /bots/biddingbot/main.py >> "$LOG_FILE" 2>&1 &
main_pid=$!

wait "$main_pid"