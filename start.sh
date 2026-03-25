#!/bin/bash

# Start script for Musikat

echo "Starting Musikat..."

# Check if virtual environment exists
if [ ! -d "backend/venv" ]; then
    echo "Creating virtual environment..."
    cd backend
    python3 -m venv venv
    cd ..
fi

# Activate virtual environment
echo "Activating virtual environment..."
source backend/venv/bin/activate

# Install dependencies if needed
if [ ! -f "backend/venv/.installed" ]; then
    echo "Installing dependencies..."
    pip install -r backend/requirements.txt
    touch backend/venv/.installed
fi

# Check if .env exists
if [ ! -f "backend/.env" ]; then
    echo "Warning: .env file not found!"
    echo "Please copy env.example to .env and configure it:"
    echo "  cp backend/env.example backend/.env"
    echo "  # Edit backend/.env with your settings"
    exit 1
fi

# Start backend (which also serves the frontend)
echo "Starting server..."
cd backend
python app.py &
SERVER_PID=$!
cd ..

echo ""
echo "=========================================="
echo "Musikat is running!"
echo "Access at: http://localhost:8000"
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop the server"

# Wait for user interrupt
trap "kill $SERVER_PID; exit" INT TERM
wait

