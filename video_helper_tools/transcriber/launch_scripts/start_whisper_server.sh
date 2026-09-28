#!/bin/bash
# Starts the Whisper server from the repository's uv environment.
cd "$(dirname "$0")/../../.." || exit 1
uv run run-whisper-server --url localhost
