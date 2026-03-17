#!/usr/bin/env python3
import fnmatch
import os
import sys
import time
from dataclasses import dataclass

from prometheus_client import Gauge, start_http_server


CLK_TCK = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
PROC_ROOT = os.getenv("PROC_ROOT", "/host_proc")
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "8000"))
PROCESS_PID_ENV = os.getenv("PROCESS_PID", "").strip()
PROCESS_NAME_ENV = os.getenv("PROCESS_NAME", "").strip()
PROCESS_PATTERN_ENV = os.getenv("PROCESS_PATTERN", "").strip()
PROCESS_SYSTEMD_SERVICE_ENV = os.getenv("PROCESS_SYSTEMD_SERVICE", "").strip()
INTERACTIVE_SELECT = os.getenv("INTERACTIVE_SELECT", "true").strip().lower() in {"1", "true", "yes", "on"}
SCRAPE_INTERVAL = float(os.getenv("SCRAPE_INTERVAL", "1.0"))


CPU_PERCENT = Gauge("observed_process_cpu_percent", "CPU usage percent of observed process")
CPU_USER_PERCENT = Gauge("observed_process_cpu_user_percent", "User CPU usage percent of observed process")
CPU_SYSTEM_PERCENT = Gauge("observed_process_cpu_system_percent", "System CPU usage percent of observed process")
RSS_BYTES = Gauge("observed_process_rss_bytes", "Resident memory bytes of observed process")
VSZ_BYTES = Gauge("observed_process_vsz_bytes", "Virtual memory bytes of observed process")
THREADS = Gauge("observed_process_threads", "Thread count of observed process")
UPTIME_SECONDS = Gauge("observed_process_uptime_seconds", "Uptime of observed process in seconds")
READ_BYTES = Gauge("observed_process_read_bytes_total", "Total bytes the process caused to be read from storage")
WRITE_BYTES = Gauge("observed_process_write_bytes_total", "Total bytes the process caused to be written to storage")
READ_SYSCALLS = Gauge("observed_process_read_syscalls_total", "Total read syscalls made by observed process")
WRITE_SYSCALLS = Gauge("observed_process_write_syscalls_total", "Total write syscalls made by observed process")
MINOR_FAULTS = Gauge("observed_process_minor_faults_total", "Minor page faults of observed process")
MAJOR_FAULTS = Gauge("observed_process_major_faults_total", "Major page faults of observed process")
OPEN_FDS = Gauge("observed_process_open_fds", "Open file descriptors of observed process")
VOLUNTARY_CTX_SWITCHES = Gauge("observed_process_voluntary_context_switches_total", "Voluntary context switches of observed process")
NONVOLUNTARY_CTX_SWITCHES = Gauge("observed_process_nonvoluntary_context_switches_total", "Nonvoluntary context switches of observed process")
PROCESS_UP = Gauge("observed_process_up", "1 if observed process exists, else 0")
PROCESS_PID_GAUGE = Gauge("observed_process_pid", "PID of observed process")


@dataclass
class ProcessTarget:
    pid: int
    comm: str


class ProcessNotFound(Exception):
    pass


def proc_path(*parts: str) -> str:
    return os.path.join(PROC_ROOT, *parts)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().strip()


def parse_stat(pid: int) -> dict:
    stat_raw = read_text(proc_path(str(pid), "stat"))
    end_comm = stat_raw.rfind(")")
    if end_comm == -1:
        raise ValueError(f"Cannot parse /proc stat for pid {pid}")
    after = stat_raw[end_comm + 2 :].split()
    # Linux procfs stat fields after comm:
    # 1 state, 12 utime, 13 stime, 20 num_threads, 22 starttime, 23 vsize, 24 rss
    utime = float(after[11])
    stime = float(after[12])
    minflt = float(after[7])
    majflt = float(after[9])
    num_threads = int(after[17])
    starttime_ticks = float(after[19])
    vsize = float(after[20])
    rss_pages = float(after[21])
    page_size = os.sysconf("SC_PAGE_SIZE")
    return {
        "utime": utime,
        "stime": stime,
        "minflt": minflt,
        "majflt": majflt,
        "num_threads": num_threads,
        "starttime_ticks": starttime_ticks,
        "vsize": vsize,
        "rss_bytes": rss_pages * page_size,
    }


def parse_io(pid: int) -> tuple[float, float, float, float]:
    read_bytes = 0.0
    write_bytes = 0.0
    syscr = 0.0
    syscw = 0.0
    try:
        for line in read_text(proc_path(str(pid), "io")).splitlines():
            if line.startswith("read_bytes:"):
                read_bytes = float(line.split(":", 1)[1].strip())
            elif line.startswith("write_bytes:"):
                write_bytes = float(line.split(":", 1)[1].strip())
            elif line.startswith("syscr:"):
                syscr = float(line.split(":", 1)[1].strip())
            elif line.startswith("syscw:"):
                syscw = float(line.split(":", 1)[1].strip())
    except (FileNotFoundError, PermissionError):
        pass
    return read_bytes, write_bytes, syscr, syscw


def parse_status_context_switches(pid: int) -> tuple[float, float]:
    voluntary = 0.0
    nonvoluntary = 0.0
    try:
        for line in read_text(proc_path(str(pid), "status")).splitlines():
            if line.startswith("voluntary_ctxt_switches:"):
                voluntary = float(line.split(":", 1)[1].strip())
            elif line.startswith("nonvoluntary_ctxt_switches:"):
                nonvoluntary = float(line.split(":", 1)[1].strip())
    except (FileNotFoundError, PermissionError):
        pass
    return voluntary, nonvoluntary


def count_open_fds(pid: int) -> float:
    try:
        return float(len(os.listdir(proc_path(str(pid), "fd"))))
    except (FileNotFoundError, PermissionError):
        return 0.0


def list_processes() -> list[ProcessTarget]:
    targets = []
    for entry in os.listdir(PROC_ROOT):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            comm = read_text(proc_path(entry, "comm"))
            targets.append(ProcessTarget(pid=pid, comm=comm))
        except FileNotFoundError:
            continue
        except PermissionError:
            continue
    targets.sort(key=lambda p: p.pid)
    return targets


def choose_by_pid(pid_text: str) -> ProcessTarget:
    pid = int(pid_text)
    comm = read_text(proc_path(str(pid), "comm"))
    return ProcessTarget(pid=pid, comm=comm)


def choose_by_name(name: str) -> ProcessTarget:
    matches = [p for p in list_processes() if p.comm == name]
    if not matches:
        raise ProcessNotFound(f"No process found with exact name '{name}'")
    return matches[0]


def choose_by_pattern(pattern: str) -> ProcessTarget:
    matches = [p for p in list_processes() if fnmatch.fnmatch(p.comm, pattern)]
    if not matches:
        raise ProcessNotFound(f"No process found matching pattern '{pattern}'")
    return matches[0]


def process_in_service(pid: int, service_name: str) -> bool:
    try:
        cgroup = read_text(proc_path(str(pid), "cgroup"))
    except (FileNotFoundError, PermissionError):
        return False
    return service_name in cgroup


def choose_by_systemd_service(service_name: str) -> ProcessTarget:
    matches = [p for p in list_processes() if process_in_service(p.pid, service_name)]
    if not matches:
        raise ProcessNotFound(f"No process found in systemd service '{service_name}'")

    # Pick the oldest PID in this service, which is commonly the MainPID.
    matches.sort(key=lambda p: p.pid)
    return matches[0]


def choose_interactive() -> ProcessTarget:
    print("=== Process Exporter Interactive Selection ===")
    print("Waehle Modus: [1] PID [2] Exakter Name [3] Muster (fnmatch, z.B. python*)")
    mode = input("Eingabe (1/2/3): ").strip()
    if mode == "1":
        value = input("PID eingeben: ").strip()
        return choose_by_pid(value)
    if mode == "2":
        value = input("Exakten Prozessnamen eingeben: ").strip()
        return choose_by_name(value)
    if mode == "3":
        value = input("Muster eingeben: ").strip()
        return choose_by_pattern(value)
    raise ProcessNotFound("Ungueltige Auswahl im interaktiven Modus")


def select_target() -> ProcessTarget:
    if PROCESS_PID_ENV:
        return choose_by_pid(PROCESS_PID_ENV)
    if PROCESS_SYSTEMD_SERVICE_ENV:
        return choose_by_systemd_service(PROCESS_SYSTEMD_SERVICE_ENV)
    if PROCESS_NAME_ENV:
        return choose_by_name(PROCESS_NAME_ENV)
    if PROCESS_PATTERN_ENV:
        return choose_by_pattern(PROCESS_PATTERN_ENV)
    if INTERACTIVE_SELECT and sys.stdin.isatty():
        return choose_interactive()
    raise ProcessNotFound(
        "Kein Zielprozess konfiguriert. Setze PROCESS_PID/PROCESS_SYSTEMD_SERVICE/PROCESS_NAME/PROCESS_PATTERN oder starte interaktiv mit -it."
    )


def get_system_uptime() -> float:
    return float(read_text(proc_path("uptime")).split()[0])


def reset_down_metrics() -> None:
    CPU_PERCENT.set(0)
    CPU_USER_PERCENT.set(0)
    CPU_SYSTEM_PERCENT.set(0)
    RSS_BYTES.set(0)
    VSZ_BYTES.set(0)
    THREADS.set(0)
    UPTIME_SECONDS.set(0)
    READ_BYTES.set(0)
    WRITE_BYTES.set(0)
    READ_SYSCALLS.set(0)
    WRITE_SYSCALLS.set(0)
    MINOR_FAULTS.set(0)
    MAJOR_FAULTS.set(0)
    OPEN_FDS.set(0)
    VOLUNTARY_CTX_SWITCHES.set(0)
    NONVOLUNTARY_CTX_SWITCHES.set(0)
    PROCESS_UP.set(0)


def monitor(target: ProcessTarget) -> None:
    print(f"Beobachte Prozess: pid={target.pid}, name={target.comm}")
    PROCESS_PID_GAUGE.set(target.pid)

    prev_cpu_total = None
    prev_utime = None
    prev_stime = None
    prev_wall = None

    while True:
        try:
            stat = parse_stat(target.pid)
            now = time.time()
            cpu_total = stat["utime"] + stat["stime"]

            cpu_percent = 0.0
            cpu_user_percent = 0.0
            cpu_system_percent = 0.0
            if prev_cpu_total is not None and prev_wall is not None:
                cpu_delta = cpu_total - prev_cpu_total
                wall_delta = now - prev_wall
                if wall_delta > 0:
                    cpu_percent = (cpu_delta / CLK_TCK) / wall_delta * 100.0
                    if prev_utime is not None and prev_stime is not None:
                        user_delta = stat["utime"] - prev_utime
                        system_delta = stat["stime"] - prev_stime
                        cpu_user_percent = (user_delta / CLK_TCK) / wall_delta * 100.0
                        cpu_system_percent = (system_delta / CLK_TCK) / wall_delta * 100.0

            prev_cpu_total = cpu_total
            prev_utime = stat["utime"]
            prev_stime = stat["stime"]
            prev_wall = now

            system_uptime = get_system_uptime()
            proc_uptime = max(system_uptime - (stat["starttime_ticks"] / CLK_TCK), 0.0)
            read_bytes, write_bytes, syscr, syscw = parse_io(target.pid)
            voluntary_ctx, nonvoluntary_ctx = parse_status_context_switches(target.pid)
            open_fds = count_open_fds(target.pid)

            CPU_PERCENT.set(cpu_percent)
            CPU_USER_PERCENT.set(cpu_user_percent)
            CPU_SYSTEM_PERCENT.set(cpu_system_percent)
            RSS_BYTES.set(stat["rss_bytes"])
            VSZ_BYTES.set(stat["vsize"])
            THREADS.set(stat["num_threads"])
            UPTIME_SECONDS.set(proc_uptime)
            READ_BYTES.set(read_bytes)
            WRITE_BYTES.set(write_bytes)
            READ_SYSCALLS.set(syscr)
            WRITE_SYSCALLS.set(syscw)
            MINOR_FAULTS.set(stat["minflt"])
            MAJOR_FAULTS.set(stat["majflt"])
            OPEN_FDS.set(open_fds)
            VOLUNTARY_CTX_SWITCHES.set(voluntary_ctx)
            NONVOLUNTARY_CTX_SWITCHES.set(nonvoluntary_ctx)
            PROCESS_UP.set(1)
        except FileNotFoundError:
            print(f"Prozess pid={target.pid} wurde beendet.")
            reset_down_metrics()
            PROCESS_PID_GAUGE.set(target.pid)
            break
        except PermissionError:
            print("Warnung: Nicht alle /proc-Werte lesbar (PermissionError).")
        except Exception as exc:
            print(f"Unerwarteter Fehler beim Lesen der Metriken: {exc}")

        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    print(f"Starte Exporter auf Port {EXPORTER_PORT} mit PROC_ROOT={PROC_ROOT}")
    start_http_server(EXPORTER_PORT)
    try:
        selected = select_target()
        monitor(selected)
    except ProcessNotFound as exc:
        print(f"Fehler bei Prozessauswahl: {exc}")
        PROCESS_UP.set(0)
        while True:
            time.sleep(5)
