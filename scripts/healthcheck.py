"""Exit 1 if the heartbeat is stale or Hubie stopped speaking. Used by systemd/cron to restart the service."""
import sys, time
from pathlib import Path

p = Path("heartbeat.txt")
state = Path("/tmp/hubie_last_count")
try:
    ts, count = p.read_text().split()
    if time.time() - float(ts) > 90:
        sys.exit("stale heartbeat")
    prev = state.read_text().split() if state.exists() else [str(time.time()), "-1"]
    if count != prev[1]:
        state.write_text(f"{time.time()} {count}")
    elif time.time() - float(prev[0]) > 300:
        sys.exit("hubie has not spoken for 5 min")
except Exception as e:
    sys.exit(f"unhealthy: {e}")
