#!/bin/bash
gitleaks detect --source . --config .gitleaks.toml --verbose --no-git
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "Gitleaks found secrets!"
    exit 1
fi
exit 0