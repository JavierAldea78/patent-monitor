#!/usr/bin/env python3
import subprocess, sys

def run(cmd):
    try:
        r = subprocess.run(cmd, text=True, capture_output=True, check=False)
        return (r.stdout or r.stderr).strip()
    except FileNotFoundError:
        return "not found"

print("Hello from Claude Code Codespaces template")
print("Python :", sys.version.split()[0])
print("Node   :", run(["node", "--version"]))
print("npm    :", run(["npm", "--version"]))
print("Git    :", run(["git", "--version"]))
print("Claude :", run(["claude", "--version"]))
