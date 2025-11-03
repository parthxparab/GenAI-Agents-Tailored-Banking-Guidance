#!/usr/bin/env bash

# Exit on any error
set -e

CHART_YAML="./helm/Chart.yaml"

if [ ! -f "$CHART_YAML" ]; then
    echo "Error: Chart.yaml not found at $CHART_YAML" >&2
    exit 1
fi

# Extract current version using grep and cut
current_version=$(grep '^version:' "$CHART_YAML" | cut -d' ' -f2)

if [ -z "$current_version" ]; then
    echo "Error: Could not find version in $CHART_YAML" >&2
    exit 1
fi

# Split version into major.minor.patch
IFS='.' read -r major minor patch <<< "$current_version"

# Increment patch version
new_patch=$((patch + 1))
new_version="${major}.${minor}.${new_patch}"

# Update Chart.yaml with new version using sed
# macOS and GNU sed have different syntaxes, so we use a temp file
temp_file=$(mktemp)
sed "s/^version: .*/version: $new_version/" "$CHART_YAML" > "$temp_file"
mv "$temp_file" "$CHART_YAML"

echo "Updated chart version from $current_version to $new_version"
echo "$new_version"