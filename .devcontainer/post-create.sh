#!/usr/bin/env bash
set -euo pipefail

echo "==> Configuring user-level npm global directory"
mkdir -p "$HOME/.npm-global"
npm config set prefix "$HOME/.npm-global"

PATH_LINE='export PATH="$HOME/.npm-global/bin:$PATH"'
if ! grep -Fq "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
  echo "$PATH_LINE" >> "$HOME/.bashrc"
fi

export PATH="$HOME/.npm-global/bin:$PATH"

echo "==> Installing Claude Code"
npm install -g @anthropic-ai/claude-code

echo "==> Tool versions"
node --version
npm --version
python3 --version
git --version
claude --version || true

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "==> ANTHROPIC_API_KEY is configured as an environment variable"
else
  echo "==> ANTHROPIC_API_KEY not configured; Claude Code can use interactive login"
fi

echo "==> post-create complete"
