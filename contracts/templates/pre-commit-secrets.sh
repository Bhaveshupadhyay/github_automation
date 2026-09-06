#!/usr/bin/env bash
# Git Pre-Commit Hook: Secret Drift Guardrail & Automatic QA Secret Synchronization
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "🔒 [PRE-COMMIT] Auditing QA secrets and contract integrity..."

# 1. Automatic In-Place Secret Re-encryption if plaintext .env.qa exists and was staged/modified
if [ -f ".env.qa" ]; then
    if git status --porcelain .env.qa | grep -q '^[ MADRCU]'; then
        echo "🔄 [PRE-COMMIT] Detected changes in local .env.qa. Encrypting to .env.qa.enc..."
        if command -v sops >/dev/null 2>&1; then
            sops --encrypt --input-type dotenv --output-type dotenv .env.qa > .env.qa.enc
            git add .env.qa.enc
            echo "✅ [PRE-COMMIT] .env.qa.enc updated and staged."
        else
            echo "⚠️  [PRE-COMMIT WARNING] 'sops' CLI not found. Skipping auto-encryption."
        fi
    fi
fi

# 2. Enforce QA Contract Schema Validation
if [ -f "qa-contract.json" ]; then
    echo "📋 [PRE-COMMIT] Validating qa-contract.json against specification..."
    if ! uv run python -m automation.qa_contract_cli qa-contract.json; then
        echo "❌ [PRE-COMMIT BLOCKED] qa-contract.json failed validation."
        exit 1
    fi
fi

# 3. Enforce CI Key-Drift Detection Guardrail
if [ -f ".env.example" ] && [ -f ".env.qa.enc" ]; then
    echo "🛡️  [PRE-COMMIT] Auditing key drift between .env.example and .env.qa.enc..."
    if ! uv run python -m automation.secret_drift_cli --example .env.example --encrypted .env.qa.enc; then
        echo "❌ [PRE-COMMIT BLOCKED] Secret key drift detected! See instructions above."
        exit 1
    fi
fi

echo "✅ [PRE-COMMIT] All secret integrity and contract validations passed!"
exit 0
