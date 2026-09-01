#!/usr/bin/env python3
import sys
import os
import subprocess

# Change to the script directory
os.chdir(os.path.dirname(__file__))

# Run uvicorn using subprocess
cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
print(f"Running: {' '.join(cmd)}")
result = subprocess.run(cmd)
sys.exit(result.returncode)