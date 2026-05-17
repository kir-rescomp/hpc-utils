#!/bin/bash
# KIR job profiler — must be sourced, not executed
# Usage: source profile_job.sh
#
# Starts a background monitor that samples CPU and memory every 10 seconds.
# Output: ${SLURM_JOB_ID}_monitor.csv in the current working directory.
# Visualise with: uv run plot_monitor.py <jobid>_monitor.csv --cpus <n>

# Guard: detect execution vs sourcing
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: profile_job.sh must be sourced, not executed." >&2
    echo "       Add this to your job script:" >&2
    echo "           source profile_job.sh" >&2
    exit 1
fi

# Guard: must be running inside a Slurm job
if [[ -z "${SLURM_JOB_ID}" ]]; then
    echo "WARNING: profile_job.sh sourced outside a Slurm job — monitor not started." >&2
    return 0
fi

_kir_monitor() {
    local outfile="${SLURM_JOB_ID}_monitor.csv"
    local cg_mem="/sys/fs/cgroup/memory/slurm/uid_${UID}/job_${SLURM_JOB_ID}"
    local cg_cpu="/sys/fs/cgroup/cpuacct/slurm/uid_${UID}/job_${SLURM_JOB_ID}"

    echo "timestamp,rss_kb,cpu_pct" > "$outfile"

    local prev_cpu_ns=0
    local prev_ts
    prev_ts=$(date +%s%N)

    while true; do
        local now_ts elapsed_ns rss rss_kb cpu_ns delta_cpu cpu_pct
        now_ts=$(date +%s%N)
        elapsed_ns=$(( now_ts - prev_ts ))
        prev_ts=$now_ts

        rss=$(cat "${cg_mem}/memory.usage_in_bytes" 2>/dev/null || echo 0)
        rss_kb=$(( rss / 1024 ))

        cpu_ns=$(cat "${cg_cpu}/cpuacct.usage" 2>/dev/null || echo 0)
        delta_cpu=$(( cpu_ns - prev_cpu_ns ))
        cpu_pct=0
        [[ $elapsed_ns -gt 0 ]] && cpu_pct=$(echo "scale=1; $delta_cpu * 100 / $elapsed_ns" | bc)
        prev_cpu_ns=$cpu_ns

        echo "$(date +%s),${rss_kb},${cpu_pct}" >> "$outfile"
        sleep 10
    done
}

_kir_monitor &
_KIR_MONITOR_PID=$!
trap "kill $_KIR_MONITOR_PID 2>/dev/null" EXIT

echo "KIR profiler started (job ${SLURM_JOB_ID}, PID ${_KIR_MONITOR_PID})" >&2
