#!/usr/bin/env python3

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from sign_manager import SignManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
LOG = logging.getLogger("sign_api")

SIGN_MAC = "FF:22:12:22:70:EE"
ANIM_DIR = Path("/home/tommy/coolledx-driver/animations")

app = FastAPI(title="CoolLEDX Sign API (persistent BLE)")

sign: Optional[SignManager] = None


class JTRequest(BaseModel):
    name: str


@app.on_event("startup")
def startup_event():
    global sign
    LOG.info("Starting SignManager")
    sign = SignManager(
        mac=SIGN_MAC,
        anim_dir=ANIM_DIR,
        device_name="CoolLEDX",
        connection_timeout=10.0,
        connection_retries=5,
        reconnect_delay=5.0,
    )
    sign.start()


@app.on_event("shutdown")
def shutdown_event():
    global sign
    if sign:
        LOG.info("Stopping SignManager")
        sign.stop()


@app.get("/animations")
def list_animations():
    if not ANIM_DIR.is_dir():
        raise HTTPException(status_code=500, detail="Animation directory missing")

    files = sorted(f for f in ANIM_DIR.iterdir() if f.suffix.lower() == ".jt")
    return {
        "ok": True,
        "animations": [
            {"name": f.stem, "filename": f.name, "path": str(f)}
            for f in files
        ],
    }


@app.post("/jt")
def play_jt(req: JTRequest):
    if not sign:
        raise HTTPException(status_code=500, detail="SignManager not initialized")

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")

    try:
        result = sign.play_jt(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOG.error("Error in /jt: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("ok", False):
        raise HTTPException(status_code=500, detail=result)

    return result


@app.post("/off")
def off():
    if not sign:
        raise HTTPException(status_code=500, detail="SignManager not initialized")

    try:
        result = sign.off(blank_name="blank")  # assumes blank.jt
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOG.error("Error in /off: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("ok", False):
        raise HTTPException(status_code=500, detail=result)

    return result


@app.post("/on")
def on():
    if not sign:
        raise HTTPException(status_code=500, detail="SignManager not initialized")

    if not sign.last_jt:
        raise HTTPException(status_code=400, detail="No last JT animation to resume")

    try:
        name = Path(sign.last_jt).stem
        result = sign.play_jt(name)
    except Exception as e:
        LOG.error("Error in /on: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("ok", False):
        raise HTTPException(status_code=500, detail=result)

    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("sign_api:app", host="0.0.0.0", port=5000, reload=False)
