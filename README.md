# Telegram Digest

A container-native automation tool that extracts messages from Telegram groups or channels and synthesizes them into highly dense, technically focused digests using Google Gemini AI.

---

## 🚀 Core Capabilities

- **Container-Native Execution**: Requires no database. Relies only on a local session file for authentication, making it ideal for ephemeral Docker runs or cron jobs.
- **Smart Fetch Logic**: 
  - Dynamically calculates API fetch limits based on unread message counts.
  - Automatically acknowledges messages as read upon successful retrieval.
  - Configurable fallback limits for inactive channels.
- **Dual Execution Modes**:
  - **Interactive CLI**: Prompts for target group selection and unread extraction parameters on the fly.
  - **Auto Mode (`--auto`)**: Runs headlessly based strictly on `.env` parameters. 
- **AI-Powered Synthesis**: Leverages Google Gemini (Flash 2.5) to compress sprawling chat histories into structured, narrative summaries.
- **Export-Only Mode**: Bypasses the LLM entirely, dumping raw, cleaned message logs directly to Markdown.

## 🛠️ Tech Stack

- **Runtime**: Python 3.12+
- **Telegram Client**: Telethon (MTProto)
- **AI Engine**: Google Generative AI SDK
- **Deployment**: Docker / Docker Compose

---

## 🏃 Quick Start

### 1. Prerequisites
- [Telegram API credentials](https://my.telegram.org/apps) (`TG_API_ID`, `TG_API_HASH`)
- [Google AI Studio API Key](https://aistudio.google.com) (`GEMINI_API_KEY`)

### 2. Setup
```bash
git clone <repo-url>
cd telegram-digest

# Initialize virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your specific credentials and limits
```

### 3. Execution

**Interactive Mode** (Manual group selection and logic configuration):
```bash
python -m src.main
```

**Auto Mode** (Headless execution using `.env` properties):
```bash
python -m src.main --auto
```

**Run Test Suite**:
```bash
pytest
```

---

## 📦 Docker Deployment 

Optimized for lightweight deployment on servers or NAS environments (e.g., Synology Container Manager).

```bash
docker-compose up --build -d
```

> **Important:** Ensure your `./data` directory is properly mounted in `docker-compose.yml`. Telethon requires persistent access to `session.session` to avoid triggering Telegram's rate limits with repeated login requests. Output artifacts (`.md` files) are also generated in this directory.

## 📂 Project Architecture

- `src/` — Core pipeline (Client, Config, Processor, Summarizer, Reporter).
- `data/` — Output directory for Markdown reports and Telethon session files.
- `tests/` — Unit test suite.
- `.env.template` — Configuration skeleton.