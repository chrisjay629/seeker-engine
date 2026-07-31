"""Run watchdog (Gambit, 2026-07-19) — the always-on backstop so a stall can NEVER be silent again.

Born the day a fetch with no total-time bound hung the flagship run for 6 hours with zero output. The
real fix was prevention (bounded fetch + governed timeouts); this is the defense-in-depth layer the
council insisted on: even if some NEW call stalls tomorrow, the run fails FAST and LOUD with a diagnosis
instead of freezing overnight.

Two pieces:
  • HEARTBEAT — the flagship stamps beat("phase name") as it progresses. Doubles as live visibility:
    runs/heartbeat.json always says which phase a run is in and when it last advanced.
  • WATCHDOG THREAD — a daemon that, if the heartbeat does not advance for `threshold` seconds
    (default 600 = 10 min, Gambit's call), dumps ALL thread stacks to runs/watchdog_dump.txt (so we
    see EXACTLY where it wedged) and then aborts the process (fail fast). A truly stalled run should
    die loud, not linger burning quota (Noor).

Prevention stays the primary guard (Vera): this must never become a crutch that hides a missing
timeout. When it fires, the dump names the culprit — fix THAT, don't just bump the threshold.
"""
from __future__ import annotations

import faulthandler
import json
import os
import threading
import time

_DEFAULT_THRESHOLD = int(os.environ.get("SEEKER_WATCHDOG_SECONDS", "600"))  # 10 min no-progress = stall
_CHECK_EVERY = 20.0

_lock = threading.Lock()
_last_beat = 0.0
_phase = "(idle)"
_thread: threading.Thread | None = None
_stop = threading.Event()
_run_dir = "runs"


def _hb_path() -> str:
    return os.path.join(_run_dir, "heartbeat.json")


_last_write = 0.0


def beat(phase: str = "") -> None:
    """Mark progress: reset the stall clock. Ultra-cheap (in-memory) so it can be called inside HOT
    loops — per finding consolidated, per fetch, per lead — not just at phase boundaries. The file
    write (for external visibility) is throttled to ~once/5s so hammering beat() costs nothing. A
    healthy run that is DOING WORK — even slow work — always advances the clock; only genuine
    no-progress (a real deadlock) lets it run out."""
    global _last_beat, _phase, _last_write
    now = time.monotonic()
    with _lock:
        _last_beat = now
        if phase:
            _phase = phase
        phase_now = _phase
        if now - _last_write < 5.0:
            return
        _last_write = now
    try:
        os.makedirs(_run_dir, exist_ok=True)
        with open(_hb_path(), "w") as f:
            json.dump({"phase": phase_now, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception:
        pass


def _watch(threshold: float) -> None:
    while not _stop.wait(_CHECK_EVERY):
        with _lock:
            idle = time.monotonic() - _last_beat
            phase = _phase
        if idle > threshold:
            path = os.path.join(_run_dir, "watchdog_dump.txt")
            try:
                os.makedirs(_run_dir, exist_ok=True)
                with open(path, "w") as f:
                    f.write(f"STALL: no progress for {idle:.0f}s (threshold {threshold:.0f}s); "
                            f"last phase = {phase!r}\n\n")
                    faulthandler.dump_traceback(file=f, all_threads=True)
            except Exception:
                pass
        # ABORT (fail fast + loud). os._exit so a wedged non-daemon worker can't keep the process
        # alive; the dump is already on disk. Nonzero code so the launcher reports failure.
            os._exit(70)


def start(*, threshold: float | None = None, run_dir: str = "runs") -> None:
    """Begin watching. Idempotent — a second call is a no-op if already running."""
    global _thread, _run_dir
    _run_dir = run_dir
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    beat("start")
    _thread = threading.Thread(target=_watch, args=(threshold or _DEFAULT_THRESHOLD,),
                               name="seeker-watchdog", daemon=True)
    _thread.start()


def stop() -> None:
    """Stop watching (call in a finally around the run so a clean finish doesn't trip the abort)."""
    _stop.set()
