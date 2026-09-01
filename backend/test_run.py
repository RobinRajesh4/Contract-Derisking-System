#!/usr/bin/env python3
import sys
import os
import subprocess

# Change to the script directory
os.chdir(os.path.dirname(__file__))

# Run uvicorn using subprocess without capturing output
cmd = [sys.executable, "-m", "uvicorn", "test_main:app", "--host", "0.0.0.0", "--port", "8001"]
print(f"Running: {' '.join(cmd)}")
result = subprocess.run(cmd)  # Don't capture output so we can see errors
sys.exit(result.returncode)