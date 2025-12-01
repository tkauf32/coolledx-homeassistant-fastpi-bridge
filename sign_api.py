#!/usr/bin/env python3
import os
import time
import logging
import subprocess
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

# ========= CONFIG =========
REPO_DIR = "/home/tommy/coolledx-driver"
VENV_PYTHON = "/home/tommy/venvs/cool-led/bin/python3"
TWEAK = os.path.join(REPO_DIR, "utils", "tweak_sign.py")

SIGN_MAC = "FF:22:12:22:70:EE"
ANIM_DIR = os.path.join(REPO_DIR, "animations")
CMD_TIMEOUT = 60.0
# ==========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = FastAPI(title="CoolLEDX Sign API")

# Last animation path in memory; could be persisted to disk later if you want
LAST_JT: Optional[str] = None


class JTRequest(BaseModel):
    name: str


def _run_cmd(extra_args: list[str]) -> tuple[int, str, str, float]:
    """
    Blocking helper: runs tweak_sign.py with the provided args.
    """
    cmd = [VENV_PYTHON, TWEAK, "-a", SIGN_MAC] + extra_args
    logging.info("Running: %s", " ".join(cmd))

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        logging.error("Timeout after %.2f sec", elapsed)
        return 124, "", "Timeout", elapsed

    elapsed = time.time() - t0
    logging.info("Finished in %.2f sec, returncode=%s", elapsed, result.returncode)

    if result.stdout.strip():
        logging.info("STDOUT: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("STDERR: %s", result.stderr.strip())

    return result.returncode, result.stdout, result.stderr, elapsed


async def run_cmd(extra_args: list[str]) -> dict:
    """
    Async wrapper for _run_cmd, executed in a thread so FastAPI stays non-blocking.
    """
    code, out, err, elapsed = await run_in_threadpool(_run_cmd, extra_args)
    return {
        "ok": code == 0,
        "returncode": code,
        "stdout": out,
        "stderr": err,
        "elapsed_sec": elapsed,
    }


@app.get("/animations")
async def list_animations():
    """
    List all .jt animations in the animations folder.
    """
    if not os.path.isdir(ANIM_DIR):
        logging.error("Animation directory does not exist: %s", ANIM_DIR)
        raise HTTPException(status_code=500, detail="Animation directory missing")

    files = sorted(
        f for f in os.listdir(ANIM_DIR) if f.lower().endswith(".jt")
    )

    animations = [
        {
            "name": os.path.splitext(f)[0],
            "filename": f,
            "path": os.path.join(ANIM_DIR, f),
        }
        for f in files
    ]

    return {"ok": True, "animations": animations}


@app.post("/jt")
async def play_jt(req: JTRequest):
    """
    Play a JT animation by name (no .jt extension).
    """
    global LAST_JT
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")

    jt_path = os.path.join(ANIM_DIR, f"{name}.jt")

    if not os.path.isfile(jt_path):
        logging.warning("Requested JT not found: %s", jt_path)
        raise HTTPException(status_code=404, detail=f"JT file not found: {jt_path}")

    logging.info("Playing JT animation: %s", jt_path)
    result = await run_cmd(["-jt", jt_path])

    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result)

    LAST_JT = jt_path
    result["jt_path"] = jt_path
    return result


@app.post("/off")
async def sign_off():
    """
    'Off' = play a 'blank' JT animation (all black).
    Requires animations/blank.jt to exist.
    """
    blank_jt = os.path.join(ANIM_DIR, "blank.jt")
    if not os.path.isfile(blank_jt):
        logging.error("blank.jt missing at %s", blank_jt)
        raise HTTPException(
            status_code=500,
            detail=f"Missing blank.jt at {blank_jt}",
        )

    logging.info("Turning sign OFF using blank.jt: %s", blank_jt)
    result = await run_cmd(["-jt", blank_jt])

    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result)

    result["jt_path"] = blank_jt
    return result


@app.post("/on")
async def sign_on():
    """
    'On' = replay the last successful JT animation (if any).
    """
    if not LAST_JT:
        logging.warning("No LAST_JT set; cannot resume.")
        raise HTTPException(
            status_code=400,
            detail="No last JT animation to resume yet.",
        )

    if not os.path.isfile(LAST_JT):
        logging.warning("LAST_JT path no longer exists: %s", LAST_JT)
        raise HTTPException(
            status_code=404,
            detail=f"Last JT file not found: {LAST_JT}",
        )

    logging.info("Replaying last JT animation: %s", LAST_JT)
    result = await run_cmd(["-jt", LAST_JT])

    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result)

    result["jt_path"] = LAST_JT
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sign_api:app",
        host="0.0.0.0",
        port=5000,
        reload=False,
    )
