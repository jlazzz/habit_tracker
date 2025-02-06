#!/bin/bash

# Exit on any error
set -e

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo "Python3 not found! Please install it first."
    exit 1
fi

# Create a virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate the virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt
