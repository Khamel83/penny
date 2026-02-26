# Penny — Intelligent Voice Middleware

Penny is a Python-based middleware system designed to bridge natural voice inputs (iPhone Voice Memos, Google Home) with Apple's native ecosystem (Reminders and Notes). It uses local transcription and LLM classification to route thoughts and tasks to the right place.

## Project Overview

- **Core Purpose:** Automate the "capture" phase of productivity. You speak naturally; Penny transcribes, classifies, and files.
- **Main Technologies:**
  - **Transcription:** `mlx-whisper` (local, high-speed transcription on Apple Silicon).
  - **Classification:** OpenRouter API (using LLMs to extract actionable items from transcripts).
  - **Routing:** AppleScript (`osascript`) for direct interaction with Apple Reminders and Apple Notes.
  - **Inputs:**
    - **iCloud Watcher:** Polls the `com.apple.VoiceMemos` directory for new recordings.
    - **Google Tasks Poller:** Polls a specific Google Tasks list (default: "My Tasks") populated by Google Home.
    - **Webhook Server:** A Flask-based listener for direct uploads.

## Architecture

- `watcher.py`: Background service monitoring local/iCloud voice memos.
- `tasks_poller.py`: Periodically fetches and processes entries from Google Tasks.
- `webhook/server.py`: HTTP endpoint for manual or external integrations.
- `core.py`: Centralized shared logic for logging, notifications, and processing pipelines.
- `classifier.py`: Interface to OpenRouter; uses a system prompt to transform raw text into JSON with categories.
- `reminders.py`: Implementation of AppleScript commands for Notes and Reminders.
- `config.py`: Configuration loader handling `config.toml` and secrets from environment variables.

## Building and Running

### Environment Setup
1. **Python Version:** 3.11+
2. **System Dependencies:** `ffmpeg` (via `brew install ffmpeg`).
3. **Python Dependencies:**
   ```bash
   pip install mlx-whisper requests watchdog flask google-api-python-client google-auth-httplib2 google-auth-oauthlib tomli
   ```
4. **macOS Permissions:** Ensure the terminal/Python has "Automation" permissions for Reminders and Notes (prompted on first run).

### Running Services
Penny is designed to run as `launchd` agents on a Mac.
- `com.penny.watcher`: Manages voice memo processing.
- `com.penny.tasks`: Manages Google Tasks polling.
- `com.penny.webhook`: Runs the Flask server.

Templates for these services are located in `launchd/`.

### Configuration
- **Settings:** Edit `config.toml` for non-sensitive options (polling intervals, list names, categories).
- **Secrets:** Set the following environment variables (typically in the `.plist` files or a local `.env` for testing):
  - `OPENROUTER_API_KEY`
  - `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
  - `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE`

## Development Conventions

- **Mac-First:** The system relies heavily on macOS-specific features (Apple Silicon MLX, AppleScript, iCloud directories).
- **LLM Prompting:** Classification logic is centralized in `classifier.py`. Categories must match the lists defined in Apple Reminders (defined in `config.toml`).
- **State Management:** Runtime state (processed file hashes, sync tokens) is kept in `~/.penny/` to ensure idempotency across restarts.
- **Logging:** Logs are stored in `~/.penny/logs/`.
- **Testing:** (TODO) No automated tests currently exist. Manual verification is performed by observing logs and checking the Reminders/Notes apps.

## Deployment

Deploy by `rsync`-ing the code to the target Mac and reloading the `launchd` agents:
```bash
# Example deployment command
rsync -av --exclude='.git' . macmini:~/penny/
ssh macmini "launchctl unload ~/Library/LaunchAgents/com.penny.*.plist && launchctl load ~/Library/LaunchAgents/com.penny.*.plist"
```
