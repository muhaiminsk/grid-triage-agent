#!/bin/bash
# Runs inside the HTCondor container as a normal user:   bash /work/collect/run_all.sh
# Submits every scenario in /work/jobs, waits until each job is held or finished, and saves the results in /work/runs.
JOBS=/work/jobs
RUNS=/work/runs
for dir in "$JOBS"/*/; do
  name=$(basename "$dir"); out="$RUNS/$name"
  rm -rf "$out"; mkdir -p "$out"; cp "$dir"* "$out"/; chmod +x "$out"/run.sh
  cd "$out" || continue
  cluster=$(condor_submit job.sub 2>&1 | sed -n 's/.*submitted to cluster \([0-9]*\).*/\1/p')
  if [ -z "$cluster" ]; then echo "$name: submit FAILED, details:"; condor_submit job.sub; continue; fi
  echo "$cluster" > cluster.txt
  echo "$name -> cluster $cluster"
done
echo "Waiting for every job to be held or to finish (up to 40 minutes; the memory jobs take the longest)..."
for i in $(seq 1 240); do
  active=$(condor_q -af JobStatus | grep -vc '^5$')
  [ "$active" -eq 0 ] && break
  sleep 10
done
for out in "$RUNS"/*/; do
  [ -f "$out/cluster.txt" ] || continue
  c=$(cat "$out/cluster.txt")
  if [ -n "$(condor_q "$c" -af ClusterId)" ]; then
    condor_q "$c" -json > "$out/ad.json"
    condor_rm "$c" > /dev/null
  else
    condor_history "$c" -json -limit 1 > "$out/ad.json"
  fi
done
echo "Done. Results are in $RUNS. Next, on your Mac:  python3 collect/export.py"
