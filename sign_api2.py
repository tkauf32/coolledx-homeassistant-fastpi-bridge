#!/usr/bin/env python3
import time
import logging
import subprocess

from flask import Flask, request, jsonify

# ---- CONFIG ----
REPO_DIR = "/home/tommy/coolledx-driver"
PYTHON = "/home/tommy/venvs/cool-led/bin/python3"
TWEAK = f"{REPO_DIR}/utils/tweak_sign.py"

SIGN_MAC = "FF:22:12:22:70:EE"  # your sign's MAC
CMD_TIMEOUT = 10  # max wall-clock per command (seconds)
BASE_ARGS = [
    "--connection-timeout", "5.0",
    "--connection-retries", "4",
]

PRESETS = {
    "status": {
        "args": ["-b", "4", "-s", "2"],
        "default_text": "All Good",
    },
    "dim": {
        "args": ["-b", "1", "-s", "1"],
        "default_text": "Dim Mode",
    },
    "alert": {
        "args": ["-b", "8", "-s", "4", "-c", "#ff0000"],
        "default_text": "ALERT",
    },
    "party": {
        "args": ["-b", "7", "-s", "3"],
        "default_text": "Party Time",
    },
}
# ---------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = Flask(__name__)

def run_cmd(extra_args):
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
    logging.info(
        "Command finished in %.2fs with returncode=%s",
        elapsed, result.returncode
    )

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
    app.logger.info("Received /off request (blackout mode)")

    # All black frame = scroller appears off
    args = [
        "-t", "",          # no text
        "-c", "#000000",   # text color
        "-C", "#000000"    # background color
    ]

    code, out, err = run_cmd(args)
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

    brightness = data.get("brightness")
    speed = data.get("speed")

    args = ["-t", text]
    if brightness is not None:
        args += ["-b", str(brightness)]
    if speed is not None:
        args += ["-s", str(speed)]

    app.logger.info(
        "Sending text=%r, brightness=%r, speed=%r",
        text, brightness, speed
    )

    code, out, err = run_cmd(args)
    ok = (code == 0)
    return jsonify({"ok": ok, "stdout": out, "stderr": err}), (200 if ok else 500)


@app.route("/preset", methods=["POST"])
def sign_preset():
    app.logger.info("Received /preset request")
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    text = (data.get("text") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "Missing 'name'"}), 400

    preset = PRESETS.get(name)
    if not preset:
        app.logger.warning("Unknown preset: %r", name)
        return jsonify({"ok": False, "error": f"Unknown preset '{name}'"}), 400

    if not text:
        text = preset.get("default_text", "")

    if not text:
        return jsonify({"ok": False, "error": "No text available for preset"}), 400

    args = ["-t", text] + preset["args"]
    app.logger.info("Running preset %r with text %r and args %s", name, text, args)

    code, out, err = run_cmd(args)
    ok = (code == 0)
    return jsonify({
        "ok": ok,
        "preset": name,
        "text": text,
        "stdout": out,
        "stderr": err,
    }), (200 if ok else 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
