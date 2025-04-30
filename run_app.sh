#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to the script's directory
cd "$SCRIPT_DIR"

# Define the virtual environment path
VENV_PATH="$SCRIPT_DIR/pyvenv_macos"

# Activate the virtual environment
if [ -f "$VENV_PATH/bin/activate" ]; then
    echo "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"
else
    echo "Error: Virtual environment activation script not found at $VENV_PATH/bin/activate" >&2
    exit 1
fi

# Run the Python application
echo "Running main.py..."
python main.py

# Deactivate the virtual environment (optional, happens automatically on script exit)
# echo "Deactivating virtual environment..."
# deactivate

echo "Application finished." 