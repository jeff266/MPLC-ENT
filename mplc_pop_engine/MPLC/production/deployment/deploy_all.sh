#!/bin/bash
set -e

echo "=========================================="
echo "MPLC PIPELINE DEPLOYMENT"
echo "=========================================="

# Pre-flight validation (skip API keys - they're set on droplets)
echo "Running pre-flight checks..."
cd "$(dirname "$0")/../.."
# Note: API keys are validated on droplets, not locally
# Just check files exist
if [ ! -f "production/enrichers/healthcare_unified.py" ]; then
    echo "ERROR: Missing healthcare_unified.py"
    exit 1
fi
if [ ! -f "production/enrichers/corporate.py" ]; then
    echo "ERROR: Missing corporate.py"
    exit 1
fi
if [ ! -f "production/workers/unified_worker.py" ]; then
    echo "ERROR: Missing unified_worker.py"
    exit 1
fi
echo "  ✓ All required files present"

echo ""
echo "Deploying to droplets..."

DROPLET1="178.128.147.34"
DROPLET2="201.79.28.183"

# Deploy enrichers
for droplet in $DROPLET1 $DROPLET2; do
    echo "  Deploying to $droplet..."

    # Create directories
    ssh root@$droplet "mkdir -p /root/enrichment/{enrichers,dependencies/{databases,models}}"

    # Copy enrichers
    scp production/enrichers/*.py root@$droplet:/root/enrichment/enrichers/

    # Copy unified worker
    scp production/workers/unified_worker.py root@$droplet:/root/enrichment/

    # Copy dependencies
    scp production/dependencies/databases/*.db root@$droplet:/root/enrichment/dependencies/databases/ 2>/dev/null || echo "    (No databases to copy)"
    scp production/dependencies/models/*.pt root@$droplet:/root/enrichment/dependencies/models/ 2>/dev/null || echo "    (No models to copy)"

    # Clear Python cache
    ssh root@$droplet "cd /root/enrichment && find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true"

    echo "    ✓ $droplet deployment complete"
done

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Run health check: ./health_check.sh"
echo "  2. Start workers: ssh root@$DROPLET1 'cd /root/enrichment && ./start_all_workers.sh'"
