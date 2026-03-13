#!/usr/bin/env bashio

bashio::log.info "Starting FixJeEnergy Add-on..."

# Start main application from the /app directory
cd /app
python3 main.py
