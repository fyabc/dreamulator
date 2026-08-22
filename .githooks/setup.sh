#!/bin/sh
# Install git hooks from .githooks/ into .git/hooks/.
# Run once after cloning or whenever hooks are updated.
#
# Usage: bash .githooks/setup.sh

set -e

HOOKS_DIR=".git/hooks"
SOURCE_DIR=".githooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "Error: $HOOKS_DIR not found — are you in the repo root?"
    exit 1
fi

for src in "$SOURCE_DIR"/*; do
    name=$(basename "$src")
    # Skip this script itself
    [ "$name" = "setup.sh" ] && continue

    dst="$HOOKS_DIR/$name"
    cp "$src" "$dst"
    echo "  installed: $dst"
done

echo ""
echo "Hooks installed. Push to main will now run lint gates."
echo "To skip in emergencies: git push --no-verify"
