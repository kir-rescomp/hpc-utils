#!/bin/bash 

# --- start background monitor ---
monitor_job() {
    local outfile="${SLURM_JOB_ID}_monitor.csv"
    local cg_mem="/sys/fs/cgroup/memory/slurm/uid_${UID}/job_${SLURM_JOB_ID}"
    local cg_cpu="/sys/fs/cgroup/cpuacct/slurm/uid_${UID}/job_${SLURM_JOB_ID}"

    echo "timestamp,rss_kb,cpu_pct" > "$outfile"

    local prev_cpu_ns=0
    local prev_ts=$(date +%s%N)

    while true; do
        local now_ts=$(date +%s%N)
        local elapsed_ns=$(( now_ts - prev_ts ))
        prev_ts=$now_ts

        local rss=$(cat "${cg_mem}/memory.usage_in_bytes" 2>/dev/null || echo 0)
        local rss_kb=$(( rss / 1024 ))

        local cpu_ns=$(cat "${cg_cpu}/cpuacct.usage" 2>/dev/null || echo 0)
        local delta_cpu=$(( cpu_ns - prev_cpu_ns ))
        local cpu_pct=0
        [[ $elapsed_ns -gt 0 ]] && cpu_pct=$(echo "scale=1; $delta_cpu * 100 / $elapsed_ns" | bc)
        prev_cpu_ns=$cpu_ns

        echo "$(date +%s),${rss_kb},${cpu_pct}" >> "$outfile"
        sleep 10
    done
}

monitor_job &
MONITOR_PID=$!
trap "kill $MONITOR_PID 2>/dev/null" EXIT
# --- end monitor ---
