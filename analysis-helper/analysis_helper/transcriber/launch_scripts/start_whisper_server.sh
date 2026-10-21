#!/bin/bash
# Starts the Whisper server from the repository's uv environment (run from the repository root).
cd "$(dirname "$0")/../../../.." || exit 1
uv run --package analysis-helper run-whisper-server --url localhost
