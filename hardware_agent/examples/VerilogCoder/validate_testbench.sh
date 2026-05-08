#!/bin/bash
# Validate a custom testbench before running VerilogCoder.
# Usage: ./validate_testbench.sh <task_id> <dataset_dir>
# Example: ./validate_testbench.sh adpll_rpa hardware_agent/examples/VerilogCoder/verilog-eval-v2/dataset_dumpall/
#
# Checks:
#   1. testbench compiles with iverilog (syntax ok)
#   2. testbench + reference implementation compiles (no duplicate modules)
#   3. simulation outputs "Mismatches: 0" (ref passes testbench)

set -e

TASK_ID=$1
DATASET_DIR=$2
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REFS_DIR="$SCRIPT_DIR/specs/refs"

if [ -z "$TASK_ID" ] || [ -z "$DATASET_DIR" ]; then
    echo "Usage: $0 <task_id> <dataset_dir>"
    exit 1
fi

# Find files
TEST_FILE=$(ls "$DATASET_DIR"/*_${TASK_ID}_test.sv 2>/dev/null | head -1)
# Use validation ref from specs/refs/ (has full module definition)
# NOT the dataset ref.sv which is comment-only to avoid duplicate module in VerilogCoder
REF_FILE="$REFS_DIR/${TASK_ID}.sv"

if [ -z "$TEST_FILE" ]; then echo "ERROR: test file not found for $TASK_ID"; exit 1; fi
if [ -z "$REF_FILE" ];  then echo "ERROR: ref file not found for $TASK_ID";  exit 1; fi

echo "Test : $TEST_FILE"
echo "Ref  : $REF_FILE"

TMP_SV=$(mktemp /tmp/validate_XXXX.sv)
TMP_VVP=$(mktemp /tmp/validate_XXXX.vvp)
trap "rm -f $TMP_SV $TMP_VVP" EXIT

# Combine testbench + ref
cat "$TEST_FILE" "$REF_FILE" > "$TMP_SV"

# Step 1: Compile
echo ""
echo "--- Step 1: iverilog compile ---"
if iverilog -o "$TMP_VVP" "$TMP_SV" 2>&1; then
    echo "PASS: compiled successfully"
else
    echo "FAIL: compile error"
    exit 1
fi

# Step 2: Simulate
echo ""
echo "--- Step 2: simulation ---"
OUTPUT=$(vvp "$TMP_VVP" 2>&1)
echo "$OUTPUT"

# Step 3: Check mismatch count
echo ""
echo "--- Step 3: check result ---"
MISMATCHES=$(echo "$OUTPUT" | grep -oP "(?<=Mismatches: )\d+" | head -1)

if [ -z "$MISMATCHES" ]; then
    echo "FAIL: 'Mismatches: N' not found in output — wrong testbench format"
    exit 1
elif [ "$MISMATCHES" -eq 0 ]; then
    echo "PASS: Mismatches = 0 — testbench valid"
else
    echo "FAIL: Mismatches = $MISMATCHES — testbench or ref has errors"
    exit 1
fi
