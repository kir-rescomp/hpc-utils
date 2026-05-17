#!/bin/bash

#SBATCH --job-name=cpu_burn
#SBATCH --cpus-per-task=6
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --output=slurmlog/cpu_burn_%j.out

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

module load Python

python3 - <<'PY'
"""
Synthetic benchmark: CPU burn + real filesystem I/O on GPFS.
6 workers run in parallel, each doing prime checking and file read/write cycles.
Writes go to ./bench_scratch/ relative to the submission directory (GPFS).
"""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import math, os, time, shutil

# ── config ────────────────────────────────────────────────────────────────────
DURATION_S   = 190          # match --time budget (seconds of actual work)
N_WORKERS    = 6            # match --cpus-per-task
PAYLOAD_MB   = 4            # write size per flush per worker (MB)
MAX_FILE_MB  = 128          # truncate file after this size to bound disk use
PRIME_BATCH  = 2000         # prime checks between each I/O cycle
SCRATCH_DIR  = Path(os.environ.get("SLURM_SUBMIT_DIR", ".")) / "bench_scratch"

# ── helpers ───────────────────────────────────────────────────────────────────
def is_prime(n):
    if n < 2: return False
    if n % 2 == 0: return n == 2
    for i in range(3, int(math.isqrt(n)) + 1, 2):
        if n % i == 0: return False
    return True

# ── worker ────────────────────────────────────────────────────────────────────
def worker(args):
    duration, idx, scratch = args
    scratch = Path(scratch)
    path    = scratch / f"worker_{idx}.bin"
    payload = os.urandom(PAYLOAD_MB * 1024 * 1024)

    end        = time.time() + duration
    n          = 10_000_000 + idx * 1_000
    primes     = 0
    bytes_read = 0
    bytes_writ = 0

    with open(path, "wb") as fh:
        while time.time() < end:

            # CPU: prime batch
            for _ in range(PRIME_BATCH):
                n += 1
                if is_prime(n):
                    primes += 1

            # Write: 2 × PAYLOAD_MB per cycle, fsynced to GPFS
            for _ in range(2):
                fh.write(payload)
                bytes_writ += len(payload)
            fh.flush()
            os.fsync(fh.fileno())

            # Read: pull back a chunk so read_bytes is non-zero
            with open(path, "rb") as rh:
                chunk = rh.read(PAYLOAD_MB * 1024 * 1024)
                bytes_read += len(chunk)

            # Truncate to keep disk use bounded
            if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
                fh.seek(0)
                fh.truncate(0)

    path.unlink(missing_ok=True)
    return {
        "worker": idx,
        "primes": primes,
        "written_mb": bytes_writ // (1024 * 1024),
        "read_mb":    bytes_read // (1024 * 1024),
    }

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    SCRATCH_DIR.mkdir(exist_ok=True)
    print(f"scratch : {SCRATCH_DIR}")
    print(f"workers : {N_WORKERS}  duration : {DURATION_S}s  payload : {PAYLOAD_MB} MB\n")

    args = [(DURATION_S, i, str(SCRATCH_DIR)) for i in range(N_WORKERS)]

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_WORKERS) as ex:
        results = list(ex.map(worker, args))
    elapsed = time.time() - t0

    for r in results:
        print(f"  worker {r['worker']}:  {r['primes']:,} primes  "
              f"wrote {r['written_mb']} MB  read {r['read_mb']} MB")

    total_w = sum(r['written_mb'] for r in results)
    total_r = sum(r['read_mb']    for r in results)
    print(f"\n  total  :  wrote {total_w} MB  read {total_r} MB  in {elapsed:.1f}s")

    # clean up scratch dir
    shutil.rmtree(SCRATCH_DIR, ignore_errors=True)

if __name__ == "__main__":
    main()
PY
