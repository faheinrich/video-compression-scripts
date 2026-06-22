#!/bin/bash

. ~/miniconda3/etc/profile.d/conda.sh
conda activate oc
python repos/whisper-server/run_minimal_whisper_server.py --url localhost