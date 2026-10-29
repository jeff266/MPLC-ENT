#!/bin/bash
# Automated health check - returns status without manual checking

DROPLET1="178.128.147.34"
DROPLET2="201.79.28.183"

echo "=========================================="
echo "PIPELINE HEALTH CHECK"
echo "=========================================="

for droplet in $DROPLET1 $DROPLET2; do
    echo ""
    echo "Droplet: $droplet"

    # Check workers running
    workers=$(ssh root@$droplet "ps aux | grep 'unified_worker' | grep -v grep | wc -l")
    echo "  Workers running: $workers"

    # Check latest log activity
    last_log=$(ssh root@$droplet "ls -t /root/enrichment/*_worker_*.log 2>/dev/null | head -1")
    if [ -n "$last_log" ]; then
        last_activity=$(ssh root@$droplet "tail -1 $last_log 2>/dev/null | cut -d' ' -f1-2" || echo "N/A")
        echo "  Last activity: $last_activity"
    else
        echo "  Last activity: No logs found"
    fi

    # Check for PROSPECTS
    prospects=$(ssh root@$droplet "grep -c 'PROSPECT' /root/enrichment/results_*.csv 2>/dev/null || echo 0")
    echo "  PROSPECTS found: $prospects"

    # Check dependencies
    db_exists=$(ssh root@$droplet "[ -f /root/enrichment/dependencies/databases/state_procurement_contracts.db ] && echo 'YES' || echo 'NO'")
    echo "  State procurement DB: $db_exists"

    model_exists=$(ssh root@$droplet "[ -f /root/enrichment/dependencies/models/yolo11n.pt ] && echo 'YES' || echo 'NO'")
    echo "  YOLO model: $model_exists"
done

echo ""
echo "=========================================="
