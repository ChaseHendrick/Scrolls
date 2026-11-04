#!/bin/bash
# Bucket Sentinel on a CPU machine (a Hugging Face Job or any Linux box with python3, numpy, numcodecs, tifffile and
# huggingface_hub): run kit sentinel in N parallel shards, then print every result file to the log, gzipped and
# base64-encoded on one "FILE name data" line each, so a run with no writable storage still returns its results.
# Public data only. Usage, from a checkout of this repository:
#   bash scripts/sentinel/job.sh controls POOL.json N          planted-defect controls, N shards
#   bash scripts/sentinel/job.sh check ITEMS.json N            every check with --image on the listed items
#   bash scripts/sentinel/job.sh meta ITEMS.json               metadata checks only (pyramid, scale, labels)
set -u
mode=$1
list=$2
n=${3:-1}
out=${SENTINEL_OUT:-/tmp/sentinel-out}
mkdir -p "$out"
started=$(date +%s)
echo "PROGRESS 0/$n start $mode $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$list") items"
pids=""
for k in $(seq 0 $((n - 1))); do
  case "$mode" in
    controls)
      python3 -m kit sentinel controls "$list" --out "$out" --shard "$k/$n" > "$out/log-$k.txt" 2>&1 & ;;
    check)
      python3 - "$list" "$k" "$n" > "$out/items-$k.txt" <<'PY'
import json, sys
items = json.load(open(sys.argv[1]))
k, n = int(sys.argv[2]), int(sys.argv[3])
print("\n".join(i for j, i in enumerate(items) if j % n == k))
PY
      # shellcheck disable=SC2046
      python3 -m kit sentinel check $(cat "$out/items-$k.txt") --image --out "$out" > "$out/log-$k.txt" 2>&1 & ;;
    meta)
      # shellcheck disable=SC2046
      python3 -m kit sentinel check $(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))))' "$list") \
        --out "$out" > "$out/log-0.txt" 2>&1 & ;;
    *) echo "unknown mode $mode"; exit 2 ;;
  esac
  pids="$pids $!"
  [ "$mode" = meta ] && break
done
done_n=0
for p in $pids; do
  wait "$p"
  done_n=$((done_n + 1))
  echo "PROGRESS $done_n/$n shard finished after $(( $(date +%s) - started )) s"
done
for f in "$out"/*; do
  [ -f "$f" ] || continue
  echo "FILE $(basename "$f") $(gzip -c "$f" | base64 -w0)"
done
echo "DONE $(( $(date +%s) - started )) s"
