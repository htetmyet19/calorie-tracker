# Calorie Tracker (web)

Upload a meal photo → a vision model (local Ollama by default, or Gemini) identifies the foods and estimates portions/calories → review, edit, and save to a daily log.

## Run

```bash
cd backend
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000. `GET /api/health` tells you whether the model is reachable.

### Model settings (`.env`)

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `OLLAMA_URL` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `gemma4:26b` | Must support vision (`ollama show <model>` lists "vision") |
| `OLLAMA_TIMEOUT` | `300` | Seconds; the first request also loads the model |
| `GEMINI_API_KEY` | | Only for `gemini`, from https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-flash-latest` | `.venv/bin/python scripts/list_models.py` lists options |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-flash-lite-latest` | Tried in order if the main model is overloaded (503), out of quota (429) or retired (404) |
| `GEMINI_RETRIES` | `2` | Retries per model on 500/503/504, with 1s, 2s backoff |

### Ollama on Windows, backend in WSL

Ollama for Windows listens on `127.0.0.1` only, which WSL's default NAT networking can't reach.
Turn on mirrored networking (Windows 11 22H2+) so `localhost` in WSL reaches Windows: add to
`%UserProfile%\.wslconfig`, then run `wsl --shutdown` in PowerShell:
```ini
[wsl2]
networkingMode=mirrored
```
(The alternative, setting `OLLAMA_HOST=0.0.0.0` on Windows and pointing `OLLAMA_URL` at the Windows IP,
also exposes Ollama to your whole network.)

## How it works

| File | Role |
|---|---|
| `app/analysis.py` | Resizes the image, picks the provider, sanity-checks the returned numbers |
| `app/ollama_client.py`, `app/gemini_client.py` | Send the image and prompt, ask for JSON matching `MealAnalysis` |
| `app/schemas.py` | Pydantic models, also used as the model's response schema |
| `app/db.py` | SQLite storage (`data/calories.db`) |
| `app/main.py` | FastAPI routes: `POST /api/analyze`, `GET/POST /api/meals`, `DELETE /api/meals/{id}` |
| `static/` | Plain HTML/CSS/JS frontend |

## Using it from the Android app

The app in `../mobile` talks to this server over your Wi-Fi; the model (or Gemini key) stays here.

1. Listen on all interfaces, not just localhost:
   ```bash
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. WSL2 hides the server behind NAT by default. Either:
   - **Mirrored networking (simplest, Windows 11 22H2+):** add to `%UserProfile%\.wslconfig`, then run `wsl --shutdown` in PowerShell:
     ```ini
     [wsl2]
     networkingMode=mirrored
     ```
   - **Or a port proxy** (PowerShell as admin; re-run when the WSL IP changes, find it with `hostname -I` in WSL):
     ```powershell
     netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<WSL IP>
     ```
   Either way, allow inbound TCP 8000 in Windows Firewall (private network only):
   ```powershell
   New-NetFirewallRule -DisplayName "Calorie tracker 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow
   ```
3. Find your PC's Wi-Fi address (`ipconfig` in Windows, the "IPv4 Address" of the Wi-Fi adapter) and enter `http://<that IP>:8000` in the app's settings, then tap "Test connection".

The server has no login, so only run it like this on a network you trust.
