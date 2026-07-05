#!/bin/bash
# save-and-push.sh — anti-perte: commit + push + update repo.tar after each phase.
#
# USAGE: ./save-and-push.sh "Phase X: description"
#
# This script:
#   1. Commits all changes with the given message.
#   2. Pushes to GitHub (origin/main) — NON-FORCE (preserves commit history).
#   3. Updates /home/sync/repo.tar (the sandbox backup) so a restart
#      restores the latest version, not an old snapshot.
#
# Run this after every phase completion. Never use --force (we want all
# commits counted on GitHub).
#
# If push fails (auth), the commit is still local — we retry push later.

set -e

MSG="${1:-auto-save: $(date -u +%FT%TZ)}"
PROJECT_DIR="/home/z/my-project"
cd "$PROJECT_DIR"

echo "=========================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] save-and-push: $MSG"
echo "=========================================="

# ── 1. Git add + commit ──
echo "[1/3] Git commit..."
git add -A
if git diff --cached --quiet; then
	echo "No changes to commit."
else
	git commit -m "$MSG" --allow-empty-message
	echo "Committed: $(git log -1 --oneline)"
fi

# ── 2. Push to GitHub (non-force) ──
echo "[2/3] Git push (origin/main, non-force)..."
if git push origin main 2>&1; then
	echo "Pushed to GitHub ✓"
else
	echo "WARNING: push failed (auth or network). Commit is local."
	echo "To fix: configure git credentials or use a PAT."
	echo "The commit is safe locally + in repo.tar."
fi

# ── 3. Update repo.tar (sandbox backup) ──
echo "[3/3] Updating sandbox backup (repo.tar)..."
tar -cf /home/sync/repo.tar.new \
	--exclude='node_modules' \
	--exclude='.venv' \
	--exclude='dev.db' \
	--exclude='__pycache__' \
	--exclude='.next' \
	--exclude='*.pyc' \
	--exclude='download' \
	--exclude='upload' \
	-C "$PROJECT_DIR" . 2>/dev/null
mv /home/sync/repo.tar.new /home/sync/repo.tar
echo "repo.tar updated ($(stat -c '%s' /home/sync/repo.tar) bytes) ✓"

echo ""
echo "=========================================="
echo "save-and-push complete."
echo "  Commit: $(git log -1 --oneline)"
echo "  Push:   see above"
echo "  Backup: /home/sync/repo.tar ($(stat -c '%s' /home/sync/repo.tar) bytes)"
echo "=========================================="
