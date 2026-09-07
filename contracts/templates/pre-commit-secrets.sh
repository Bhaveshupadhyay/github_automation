#!/usr/bin/env bash
# Git Pre-Commit Hook: Secret Drift Guardrail & Automatic QA Secret Synchronization
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "🔒 [PRE-COMMIT] Auditing QA secrets and contract integrity..."

# 1. Block any attempt to stage plaintext secrets
if git diff --cached --name-only | grep -qE '^(\.env|\.env\.qa)$'; then
    echo "❌ [PRE-COMMIT BLOCKED] Plaintext secret file (.env or .env.qa) is staged in the Git index!"
    echo "   Raw secrets must never be committed to Git. Unstage using: git reset HEAD .env.qa"
    exit 1
fi

# 2. Automatic In-Place Secret Re-encryption if local .env.qa exists and was modified
if [ -f ".env.qa" ]; then
    if git diff --name-only | grep -qE '^\.env\.qa$'; then
        echo "🔄 [PRE-COMMIT] Detected uncommitted modifications in local .env.qa."
        if ! command -v sops >/dev/null 2>&1; then
            echo "❌ [PRE-COMMIT BLOCKED] .env.qa was modified but 'sops' CLI is not installed."
            echo "   Please install SOPS (e.g. brew install sops) to encrypt secrets before committing."
            exit 1
        fi
        echo "🔒 [PRE-COMMIT] Encrypting .env.qa to .env.qa.enc..."
        sops --encrypt --input-type dotenv --output-type dotenv .env.qa > .env.qa.enc
        git add .env.qa.enc
        # Ensure plaintext .env.qa remains untracked/unstaged
        git reset HEAD .env.qa >/dev/null 2>&1 || true
        echo "✅ [PRE-COMMIT] .env.qa.enc updated and staged."
    fi
fi

# 3. Enforce QA Contract Schema Validation
if [ -f "qa-contract.json" ]; then
    echo "📋 [PRE-COMMIT] Validating qa-contract.json against specification..."
    if ! uv run python -m automation.qa_contract_cli qa-contract.json; then
        echo "❌ [PRE-COMMIT BLOCKED] qa-contract.json failed validation."
        exit 1
    fi
fi

# 4. Enforce CI Key-Drift Detection Guardrail (runs whenever .env.example exists)
if [ -f ".env.example" ]; then
    echo "🛡️  [PRE-COMMIT] Auditing secret key drift against .env.example..."
    if ! uv run python -m automation.secret_drift_cli --example .env.example --encrypted .env.qa.enc; then
        echo "❌ [PRE-COMMIT BLOCKED] Secret key drift detected! See instructions above."
        exit 1
    fi
fi

echo "✅ [PRE-COMMIT] All secret integrity and contract validations passed!"
exit 0
