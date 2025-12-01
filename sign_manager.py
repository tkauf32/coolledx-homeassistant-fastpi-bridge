#!/usr/bin/env python3

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal

from bleak.exc import BleakError  # comes from bleak

from coolledx.client import Client
from coolledx.commands import SetJT  # we only need JT for now

LOG = logging.getLogger("sign_manager")

JobKind = Literal["jt"]


@dataclass
class Job:
    kind: JobKind
    jt_path: Path
    future: asyncio.Future  # resolves to dict with {"ok": bool, ...}


class SignManager:
    """
    Persistent BLE connection to the CoolLEDX sign.

    - Starts an asyncio loop on a background thread.
    - Opens one long-lived Client(...) connection (`async with Client(...)`).
    - Processes a queue of jobs (JT uploads) over that connection.
    - Auto-reconnects if the connection dies.
    """

    def __init__(
        self,
        mac: str,
        anim_dir: Path,
        device_name: str = "CoolLEDX",
        connection_timeout: float = 10.0,
        connection_retries: int = 5,
        reconnect_delay: float = 5.0,
    ) -> None:
        self.mac = mac
        self.anim_dir = Path(anim_dir)

        self._client_config = {
            "address": self.mac,
            "device_name": device_name,
            "connection_timeout": connection_timeout,
            "connection_retries": connection_retries,
        }

        self._reconnect_delay = reconnect_delay

        # Async machinery
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="SignLoop",
            daemon=True,
        )

        self._job_queue: asyncio.Queue[Job] = asyncio.Queue()
        self._connected = asyncio.Event()
        self._stop = asyncio.Event()

        # Track last animation
        self.last_jt: Optional[Path] = None

    # ---------- lifecycle ----------

    def start(self) -> None:
        LOG.info("Starting SignManager loop thread")
        self._thread.start()
        # Start the client management task on the loop
        asyncio.run_coroutine_threadsafe(self._run_client_forever(), self._loop)

    def stop(self) -> None:
        LOG.info("Stopping SignManager")
        def _stop():
            self._stop.set()
            for task in asyncio.all_tasks(loop=self._loop):
                task.cancel()
            self._loop.stop()

        self._loop.call_soon_threadsafe(_stop)
        self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    # ---------- public sync API (called from FastAPI) ----------

    def play_jt(self, name: str) -> dict:
        """
        Play a JT animation by basename (no .jt extension).

        Schedules a job on the asyncio loop and blocks until it is done.
        """
        name = name.strip()
        if not name:
            raise ValueError("Empty JT name")

        jt_path = (self.anim_dir / f"{name}.jt").resolve()
        if not jt_path.is_file():
            raise FileNotFoundError(f"JT not found: {jt_path}")

        fut = asyncio.run_coroutine_threadsafe(
            self._submit_job(kind="jt", jt_path=jt_path),
            self._loop,
        )
        result = fut.result()
        if result.get("ok"):
            self.last_jt = jt_path
        return result

    def off(self, blank_name: str = "blank") -> dict:
        """
        "Off" == play a blank JT (e.g. blank.jt).
        """
        return self.play_jt(blank_name)

    # ---------- internal async helpers ----------

    async def _submit_job(self, kind: JobKind, jt_path: Path) -> dict:
        """
        Enqueue a Job and wait for it to complete.
        """
        job_future: asyncio.Future = self._loop.create_future()
        job = Job(kind=kind, jt_path=jt_path, future=job_future)
        await self._job_queue.put(job)
        # Wait for job result (set by _process_job)
        return await job_future

    async def _run_client_forever(self) -> None:
        """
        Outer loop: keeps a Client context open, reconnects on failure.
        """
        while not self._stop.is_set():
            LOG.info("Attempting BLE connect to %s", self.mac)
            try:
                async with Client(**self._client_config) as client:
                    LOG.info("Connected to sign")
                    self._connected.set()
                    # Process jobs until stop or an exception
                    try:
                        while not self._stop.is_set():
                            job = await self._job_queue.get()
                            await self._process_job(client, job)
                    finally:
                        self._connected.clear()
                        LOG.info("Client context exiting, will reconnect")
            except (TimeoutError, BleakError, asyncio.CancelledError) as e:
                LOG.warning("BLE connection error: %s", e)
                self._connected.clear()
                # Reject any pending jobs in the queue until we reconnect
                # (optional; here we just reconnect and leave jobs queued)
            except Exception as e:
                LOG.error("Unexpected error in client loop: %s", e, exc_info=True)
                self._connected.clear()

            if not self._stop.is_set():
                LOG.info("Reconnecting in %.1f seconds", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)

    async def _process_job(self, client: Client, job: Job) -> None:
        """
        Execute a single Job using the connected client.
        """
        try:
            if job.kind == "jt":
                LOG.info("Sending JT: %s", job.jt_path)

                # Minimal SetJT usage; same command tweak_sign.py uses,
                # but we only pass the path and let defaults handle alignment.
                cmd = SetJT(str(job.jt_path))
                await client.send_command(cmd)

                result = {
                    "ok": True,
                    "kind": job.kind,
                    "jt_path": str(job.jt_path),
                }
                job.future.set_result(result)
            else:
                raise ValueError(f"Unknown job kind: {job.kind}")
        except Exception as e:
            LOG.error("Error while processing job %s: %s", job, e, exc_info=True)
            if not job.future.done():
                job.future.set_result(
                    {
                        "ok": False,
                        "kind": job.kind,
                        "jt_path": str(job.jt_path),
                        "error": str(e),
                    }
                )
            # Dropping out of the inner loop will cause reconnect;
            # raising here will be caught by _run_client_forever.
            raise
