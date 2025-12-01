#!/usr/bin/env python3
import time
import logging
import subprocess

from flask import Flask, request, jsonify

# ---- CONFIG ----
REPO_DIR = "/home/tommy/coolledx-driver"
PYTHON = "/home/tommy/venvs/cool-led/bin/python3"
TWEAK = f"{REPO_DIR}/utils/tweak_sign.py"

SIGN_MAC = "FF:22:12:22:70:EE"  # <-- your MAC
CMD_TIMEOUT = 10  # max wall-clock per command (HTTP timeout)
BASE_ARGS = [
    "--connection-timeout", "3.0",
    "--connection-retries", "2",
]
# ---------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = Flask(__name__)

def run_cmd(extra_args):
    # extra_args is e.g. ["-t", "Hello"] or ["-b", "0"]
    cmd = [PYTHON, TWEAK, "-a", SIGN_MAC] + BASE_ARGS + extra_args
    logging.info("Running command: %s", " ".join(cmd))

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - t0
        logging.error("Command TIMEOUT after %.2fs: %s", elapsed, e)
        return 124, "", f"Timeout after {elapsed:.2f}s"

    elapsed = time.time() - t0
    logging.info("Command finished in %.2fs with returncode=%s", elapsed, result.returncode)

    if result.stdout.strip():
        logging.info("STDOUT: %s", result.stdout.strip())
    if result.stderr.strip():
        logging.warning("STDERR: %s", result.stderr.strip())

    return result.returncode, result.stdout, result.stderr


@app.route("/on", methods=["POST"])
def sign_on():
    app.logger.info("Received /on request")
    code, out, err = run_cmd(["-t", "WELCOME"])
    ok = (code == 0)
    return jsonify({"ok": ok, "stdout": out, "stderr": err}), (200 if ok else 500)


@app.route("/off", methods=["POST"])
def sign_off():
    app.logger.info("Received /off request")
    code, out, err = run_cmd(["-b", "0"])
    ok = (code == 0)
    return jsonify({"ok": ok, "stdout": out, "stderr": err}), (200 if ok else 500)


@app.route("/message", methods=["POST"])
def sign_message():
    app.logger.info("Received /message request")
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        app.logger.warning("No text provided in /message payload")
        return jsonify({"ok": False, "error": "Missing 'text'"}), 400

    app.logger.info("Sending text to sign: %r", text)
    code, out, err = run_cmd(["-t", text])
    ok = (code == 0)
    return jsonify({"ok": ok, "stdout": out, "stderr": err}), (200 if ok else 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
