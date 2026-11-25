"""Stand-in for a Kane CLI run that never ends: like kane-cli, it starts a child process (Kane's runner and browser
driver) that inherits stdout and keeps it open. Writes the child's pid to the file named in HANG_KANE_PIDFILE."""
import os
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
if os.environ.get("HANG_KANE_PIDFILE"):
    with open(os.environ["HANG_KANE_PIDFILE"], "w") as f:
        f.write(str(child.pid))
print('{"type": "stream_start", "v": 1}', flush=True)
time.sleep(120)
