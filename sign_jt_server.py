#!/usr/bin/env python3
import os
import time
import logging
import subprocess
from flask import Flask, request, jsonify

# ===== CONFIG =====
REPO_DIR = "/home/tommy/coolledx-driver"
VENV_PYTHON = "/home/tommy/venvs/cool-led/bin/python3"
TWEAK = os.path.join(REPO_DIR, "utils", "tweak_sign.py")

SIGN_MAC = "FF:22:12:22:70:EE"
ANIM_DIR = os.path.join(REPO_DIR, "animations")
CMD_TIMEOUT = 60   # generous but not infinite

LAST_JT = None
# ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = Flask(__name__)


def run_cmd(extra_args):
    cmd = [VENV_PYTHON, TWEAK, "-a", SIGN_MAC] + extra_args
    logging.info("Running: %s", " ".join(cmd))

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        logging.error("Timeout after %.2f sec", elapsed)
        return 124, "", "Timeout"

    elapsed = time.time() - t0
    logging.info("Finished in %.2f sec, returncode=%s", elapsed, result.returncode)

    if result.stdout.strip():
        logging.info("STDOUT: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("STDERR: %s", result.stderr.strip())

    return result.returncode, result.stdout, result.stderr


@app.route("/off", methods=["POST"])
def sign_off():
    """
    Turn the sign visually OFF by sending an all-black frame.
    """
    logging.info("Received /off request")
    args = [
        "-t", "",
        "-c", "#000000",
        "-C", "#000000"
    ]
    code, out, err = run_cmd(args)
    return jsonify({"ok": code == 0, "stdout": out, "stderr": err}), (200 if code == 0 else 500)


@app.route("/on", methods=["POST"])
def sign_on():
    """
    Resume last JT animation if available.
    """
    global LAST_JT
    logging.info("Received /on request")

    if not LAST_JT or not os.path.isfile(LAST_JT):
        logging.warning("No last animation to resume.")
        return jsonify({"ok": False, "error": "No last JT animation"}), 400

    args = ["-jt", LAST_JT]
    code, out, err = run_cmd(args)

    return jsonify({
        "ok": code == 0,
        "jt_path": LAST_JT,
        "stdout": out,
        "stderr": err
    }), (200 if code == 0 else 500)


@app.route("/animations", methods=["GET"])
def list_animations():
    """
    Return all .jt files in animations folder.
    """
    logging.info("Received /animations request")

    if not os.path.isdir(ANIM_DIR):
        return jsonify({"ok": False, "error": "Animation dir missing"}), 500

    files = sorted([
        f for f in os.listdir(ANIM_DIR)
        if f.lower().endswith(".jt")
    ])

    return jsonify({
        "ok": True,
        "animations": [
            {
                "name": f.rsplit(".", 1)[0],
                "filename": f,
                "path": os.path.join(ANIM_DIR, f),
            }
            for f in files
        ]
    }), 200


@app.route("/jt", methods=["POST"])
def play_jt():
    """
    Play a JT file by name (filename without .jt)
    Body: { "name": "heart-wings" }
    """
    global LAST_JT
    logging.info("Received /jt request")

    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Missing 'name'"}), 400

    jt_path = os.path.join(ANIM_DIR, f"{name}.jt")

    if not os.path.isfile(jt_path):
        return jsonify({"ok": False, "error": f"JT file not found: {jt_path}"}), 404

    args = ["-jt", jt_path]
    code, out, err = run_cmd(args)

    if code == 0:
        LAST_JT = jt_path

    return jsonify({
        "ok": code == 0,
        "jt_path": jt_path,
        "stdout": out,
        "stderr": err
    }), (200 if code == 0 else 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
