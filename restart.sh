#!/usr/bin/env bash
# Stop any running bot (clean: cancels its orders) and start exactly one new one.
cd "$(dirname "$0")"
pkill -TERM -f "python -u bot.py"; sleep 5; pkill -KILL -f "python -u bot.py"
nohup .venv/bin/python -u bot.py >> bot.log 2>&1 &
sleep 2; pgrep -fl "python -u bot.py"
