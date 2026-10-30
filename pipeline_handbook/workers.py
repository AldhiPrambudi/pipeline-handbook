"""Isolate trusted adapter failures and bound CPU, address space and wall time.

This is fault/resource isolation, not an OS sandbox for untrusted executable code.
Only explicitly trusted project components can enter this worker.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import multiprocessing
import os
from pathlib import Path
import sys
import sysconfig
import time

from .model import Context
from .security import within


def _inspection_guards(config, adapter):
    """Application-level metadata-only adapter permissions (not an OS sandbox).

    Payloads are already in memory. Adapters can read their trusted component and
    installed parser modules, but cannot open targets/output, write files, start
    processes, access sockets or evaluate source text. Native malicious code is
    outside this trust model; adapters must still be reviewed.
    """
    package = Path(__file__).parent.resolve()
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    component = Path(adapter["_path"]).resolve() if adapter.get("_path") else None
    roots = [Path(source["_root"]).resolve() for source in config["sources"]]
    output = Path(config["output"]["_root"]).resolve()

    def permitted(path):
        path = Path(path).resolve()
        if within(path, package) or component == path:
            return True
        if any(within(path, root) for root in roots) or within(path, output):
            return False
        return within(path, stdlib)

    def audit(event, arguments):
        if event == "open":
            path, mode, flags = arguments
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            if flags & write_flags or mode and any(character in mode for character in "wax+"):
                raise PermissionError("adapter filesystem writes prohibited")
            if not isinstance(path, int) and not permitted(path):
                raise PermissionError("adapter read outside trusted parser components prohibited")
        elif event == "exec":
            filename = arguments[0].co_filename
            if not filename.startswith("<frozen ") and (filename.startswith("<") or not permitted(filename)):
                raise PermissionError("adapter target/dynamic code execution prohibited")
        elif event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {
            "os.system", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn",
            "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.symlink", "os.link",
            "os.chmod", "os.chown", "os.truncate", "os.utime", "os.chdir", "os.putenv",
        }:
            raise PermissionError("adapter operation exceeds metadata-only permissions")
    sys.addaudithook(audit)


def _worker(connection, artifact, technology, config, adapter, rule, collected_at):
    try:
        # Discard adapter output, including import-time/native prints. Only the
        # redacted structured result may leave the worker through its pipe.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
        try:
            import resource
            cpu = math.ceil(config["budgets"]["adapter_timeout_seconds"]) + 1
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            memory = config["budgets"]["adapter_memory_mb"] * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        except (ImportError, ValueError, OSError):
            # RLIMIT_AS is not supported by every OS; wall time and input/node
            # limits always remain active. Public docs describe this boundary.
            pass
        # urllib.parse initializes trusted standard-library namedtuple classes
        # with generated code. Initialize this reviewed parser dependency before
        # the guard, rather than allowing arbitrary '<string>' execution later.
        import urllib.parse
        _inspection_guards(config, adapter)
        if "module" in adapter:
            module = importlib.import_module(adapter["module"])
        else:
            spec = importlib.util.spec_from_file_location("handbook_trusted_component", adapter["_path"])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        ctx = Context(artifact, technology, config, adapter, rule, collected_at)
        module.analyze(artifact, ctx)
        connection.send({"ok": True, "result": ctx.result()})
    except BaseException as error:
        # Exception strings can contain SQL literals or credentials; never persist.
        connection.send({"ok": False, "error": type(error).__name__})
    finally:
        connection.close()


def run_adapter(artifact, technology, config, adapter, rule, collected_at, deadline):
    remaining = min(config["budgets"]["adapter_timeout_seconds"], deadline - time.monotonic())
    if remaining <= 0:
        return {"ok": False, "error": "ScanTimeout"}
    mp = multiprocessing.get_context("spawn")
    reader, writer = mp.Pipe(duplex=False)
    process = mp.Process(target=_worker, args=(writer, artifact, technology, config, adapter, rule, collected_at), daemon=True)
    process.start()
    writer.close()
    try:
        if reader.poll(remaining):
            try:
                result = reader.recv()
            except EOFError:
                result = {"ok": False, "error": "AdapterWorkerExited"}
        else:
            result = {"ok": False, "error": "AdapterTimeout"}
    finally:
        reader.close()
        process.join(0.2)
        if process.is_alive():
            process.terminate()
            process.join(0.2)
        if process.is_alive():
            process.kill()
            process.join(0.2)
        process.close()
    return result
