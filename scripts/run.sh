#!/bin/bash
set -e

cd /home/feifeichouchou/happy_lad_v2
/home/feifeichouchou/happy_lad_v2/.venv/bin/python -m app.main --config configs/cameras.yaml --host 0.0.0.0 --port 5000
