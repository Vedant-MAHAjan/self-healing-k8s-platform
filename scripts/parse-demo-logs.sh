#!/bin/bash
# Parse and prettify self-healing operator logs for demo

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

parse_line() {
    local line="$1"
    
    # Extract event type
    if echo "$line" | grep -q '"event":'; then
        event=$(echo "$line" | grep -o '"event":"[^"]*"' | cut -d'"' -f4)
        
        case "$event" in
            "operator_starting")
                echo -e "${CYAN}🚀 Operator starting...${NC}"
                ;;
            "ai_engine_initialized")
                provider=$(echo "$line" | grep -o '"provider":"[^"]*"' | cut -d'"' -f4)
                model=$(echo "$line" | grep -o '"model":"[^"]*"' | cut -d'"' -f4)
                echo -e "${GREEN}✅ AI Engine initialized: ${BOLD}$provider${NC} (model: $model)"
                ;;
            "pod_issue_detected")
                issue_type=$(echo "$line" | grep -o '"issue_type":"[^"]*"' | cut -d'"' -f4)
                name=$(echo "$line" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
                namespace=$(echo "$line" | grep -o '"namespace":"[^"]*"' | cut -d'"' -f4)
                echo ""
                echo -e "${RED}🐛 Issue Detected: ${BOLD}$issue_type${NC}"
                echo -e "   📦 Pod: ${YELLOW}$namespace/$name${NC}"
                ;;
            "requesting_ai_diagnosis")
                issue_id=$(echo "$line" | grep -o '"issue_id":"[^"]*"' | cut -d'"' -f4)
                echo -e "${BLUE}🤖 Requesting AI diagnosis...${NC}"
                ;;
            "ai_diagnosis_started")
                echo -e "${BLUE}   🧠 AI analyzing logs and events...${NC}"
                ;;
            "ai_diagnosis_completed")
                strategy=$(echo "$line" | grep -o '"strategy":"[^"]*"' | cut -d'"' -f4)
                confidence=$(echo "$line" | grep -o '"confidence":[0-9.]*' | cut -d':' -f2)
                duration=$(echo "$line" | grep -o '"duration_seconds":[0-9.]*' | cut -d':' -f2)
                confidence_pct=$(echo "$confidence * 100" | bc 2>/dev/null || echo "$confidence")
                echo -e "${GREEN}💡 AI Diagnosis Complete (${duration}s):${NC}"
                echo -e "   📋 Strategy: ${BOLD}$strategy${NC}"
                echo -e "   📊 Confidence: ${BOLD}${confidence_pct}%${NC}"
                ;;
            "executing_remediation")
                if echo "$line" | grep -q '"action_id"'; then
                    strategy=$(echo "$line" | grep -o '"strategy":"[^"]*"' | cut -d'"' -f4)
                    echo -e "${YELLOW}🔧 Applying fix: ${BOLD}$strategy${NC}"
                fi
                ;;
            "remediation_successful")
                if echo "$line" | grep -q 'strategy_manager'; then
                    echo -e "${GREEN}✅ Remediation successful!${NC}"
                fi
                ;;
            "increase_resources_successful")
                multiplier=$(echo "$line" | grep -o '"multiplier":[0-9.]*' | cut -d':' -f2)
                echo -e "${GREEN}   📈 Resources increased by ${multiplier}x${NC}"
                ;;
            "pod_restart_successful")
                pod=$(echo "$line" | grep -o '"pod":"[^"]*"' | cut -d'"' -f4)
                echo -e "${GREEN}   🔄 Pod restarted: $pod${NC}"
                ;;
            "pod_deleted")
                pod=$(echo "$line" | grep -o '"pod":"[^"]*"' | cut -d'"' -f4)
                echo -e "   🗑️  Old pod deleted: $pod"
                ;;
        esac
    fi
}

# Read from stdin
while IFS= read -r line; do
    parse_line "$line"
done
