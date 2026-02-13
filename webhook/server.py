#!/usr/bin/env python3
"""
Penny Webhook Server
Receives audio from iOS Shortcuts, transcribes on macmini, sends to Telegram.
"""
import os
import tempfile
import logging
from flask import Flask, request, jsonify
import requests
import subprocess

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MACMINI_HOST = "macmini-ts"

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/upload', methods=['POST'])
def upload():
    """Receive audio file, transcribe on macmini, send to Telegram."""
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file"}), 400
    
    audio_file = request.files['audio']
    log.info(f"Received audio: {audio_file.filename}")
    
    with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as f:
        audio_file.save(f.name)
        temp_path = f.name
    
    try:
        remote_path = f"/tmp/penny_{os.path.basename(temp_path)}"
        
        # SCP to macmini
        subprocess.run(["scp", temp_path, f"{MACMINI_HOST}:{remote_path}"], 
                      check=True, capture_output=True, timeout=30)
        
        # Transcribe on macmini using a script approach
        python_script = f'''
import mlx_whisper
result = mlx_whisper.transcribe("{remote_path}", path_or_hf_repo="mlx-community/whisper-large-v3-turbo")
print(result["text"])
'''
        # Write script to remote temp file and execute
        script_path = f"/tmp/transcribe_{os.path.basename(temp_path)}.py"
        scp_result = subprocess.run(
            ["ssh", MACMINI_HOST, f"cat > {script_path}"],
            input=python_script.encode(),
            capture_output=True,
            timeout=10
        )
        
        # Run the script
        result = subprocess.run(
            ["ssh", MACMINI_HOST, 
             "export PATH=/opt/homebrew/bin:$PATH &&",
             "source ~/penny/venv/bin/activate &&",
             f"python3 {script_path}"],
            capture_output=True, text=True, timeout=120
        )
        transcript = result.stdout.strip()
        
        if not transcript:
            log.error(f"Transcription failed: {result.stderr}")
            transcript = "Transcription failed"
        else:
            log.info(f"Transcript: {transcript[:100]}...")
        
        send_to_telegram(transcript)
        
        # Cleanup remote
        subprocess.run(["ssh", MACMINI_HOST, "rm", "-f", remote_path, script_path], capture_output=True)
        
        return jsonify({"status": "ok", "transcript": transcript[:200]})
    
    except Exception as e:
        log.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(temp_path)

def send_to_telegram(transcript):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured")
        return
    
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🎤 Voice memo:\n\n{transcript}"},
            timeout=30
        )
        resp.raise_for_status()
        log.info("Sent to Telegram")
    except Exception as e:
        log.error(f"Telegram error: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5678)
