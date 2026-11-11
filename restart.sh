#!/usr/bin/env bash
# Stop ANY running bot (bot.py or bot2.py; clean shutdown cancels orders) and start exactly one.
# Usage: ./restart.sh [bot2.py|bot.py]   (default bot2.py)
cd "$(dirname "$0")"
BOT="${1:-bot2.py}"
pkill -TERM -f -- "-u bot2?.py"; sleep 5; pkill -KILL -f -- "-u bot2?.py"
nohup .venv/bin/python -u "$BOT" >> "${BOT%.py}.log" 2>&1 &
sleep 2; pgrep -fl -- "-u bot"; true
