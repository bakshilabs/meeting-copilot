#!/bin/zsh
# Start Meeting Copilot (uses your Claude subscription via Claude Code), for example:
#   ./run.sh --library ~/Documents/Library
cd "${0:A:h}"
[[ -x bin/systap ]] || swiftc -O -swift-version 5 systap/main.swift -o bin/systap
uv sync --quiet
exec .venv/bin/python -m copilot.server "$@"
