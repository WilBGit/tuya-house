#!/bin/bash
# Tuya House API Server
# Usage: ./start.sh [--ngrok]
#   --ngrok  Also start ngrok tunnel for Alexa skill endpoint

cd "$(dirname "$0")"

# Use the project venv
VENV="/path/to/project/ssd/.venv"
source "$VENV/bin/activate"

: "${TUYA_API_KEY:?TUYA_API_KEY must be set in the environment}"
: "${TUYA_API_SECRET:?TUYA_API_SECRET must be set in the environment}"
export TUYA_REGION="us"
export DEVICES_JSON="../tuya_devices.json"
export PORT="${PORT:-8321}"

echo "Starting Tuya House API on port $PORT..."

if [[ "$1" == "--ngrok" ]]; then
    echo "Starting ngrok tunnel..."
    ngrok http $PORT --log=stdout &
    NGROK_PID=$!
    sleep 2
    echo "Ngrok URL: check https://dashboard.ngrok.com/endpoints"
    echo "Use the ngrok https URL as your Alexa skill endpoint"
fi

python server.py
