import random
from datetime import UTC, datetime


def shell_script(script: str, args: dict = None) -> dict:
    """Stub shell script executor. Simulates running a diagnostic shell script on a remote host."""
    if args is None:
        args = {}

    now = datetime.now(UTC)

    script_lower = script.lower()

    if "df" in script_lower or "disk" in script_lower:
        stdout = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       200G  188G  6.5G  97% /\n"
            "/dev/sdb1       500G   82G  394G  18% /data\n"
            "tmpfs           7.8G  2.1G  5.7G  27% /dev/shm\n"
        )
    elif "top" in script_lower or "cpu" in script_lower or "ps" in script_lower:
        pid = random.randint(1000, 65000)
        cpu_pct = round(random.uniform(85, 99), 1)
        stdout = (
            f"PID    USER  %CPU  %MEM  COMMAND\n"
            f"{pid}   app   {cpu_pct}  12.3  java -Xmx4g -jar app.jar\n"
            f"{pid+1}  app    4.2   1.1  node server.js\n"
        )
    elif "free" in script_lower or "mem" in script_lower:
        stdout = (
            "              total        used        free      shared     buffers\n"
            "Mem:       16348256    15890120      458136      125440      102400\n"
            "-/+ buffers:            15787720     560536\n"
            "Swap:       4194304      922688     3271616\n"
        )
    elif "netstat" in script_lower or "ss " in script_lower or "port" in script_lower:
        stdout = (
            "Proto  Local Address          Foreign Address        State\n"
            "tcp    0.0.0.0:8080           0.0.0.0:*              LISTEN\n"
            f"tcp    10.0.1.5:8080         10.0.0.{random.randint(2,254)}:43210  ESTABLISHED\n"
            f"tcp    127.0.0.1:5432        127.0.0.1:{random.randint(30000,60000)}  TIME_WAIT\n"
        )
    elif "kubectl" in script_lower or "k8s" in script_lower:
        stdout = (
            "NAME                           READY   STATUS             RESTARTS   AGE\n"
            f"app-pod-{random.randint(100,999)}abc           0/1     CrashLoopBackOff   {random.randint(5,20)}         2h\n"
            f"worker-pod-{random.randint(100,999)}def         1/1     Running            0          3d\n"
        )
    else:
        stdout = f"Script executed successfully at {now.isoformat()}Z\nExit code: 0\n"

    return {
        "script": script,
        "args": args,
        "stdout": stdout,
        "stderr": "",
        "returncode": 0,
        "executed_at": now.isoformat() + "Z",
    }


execute = shell_script
