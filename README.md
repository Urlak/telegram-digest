# 🤖 Telegram Digest

An automated tool to extract messages from Telegram groups and channels, summarizing them into "human-engineering" technical digests using Google Gemini AI.

---

## 🚀 Key Features

- **Automated Extraction**: Fetches messages from specified Telegram groups/channels within a configurable time window.
- **AI-Powered Summarization**: Uses Google Gemini (Flash 2.5) to create narrative, technical summaries.
- **Smart Grouping**: Automatically handles multiple target groups and saves individual `.md` reports for each.
- **Persistence**: Tracks processed messages in a local SQLite database to avoid redundant summarization.
- **Refined AI Style**: Generates "Human-Engineering" digests—narrative, dense, and technically focused.

## 🛠️ Tech Stack

- **Python 3.12+**
- **Telethon**: Telegram MTProto client.
- **Google Generative AI**: Summarization engine.
- **SQLite**: Local message tracking and caching.
- **Docker**: Ready for deployment on NAS or servers.

## 🏃 Quick Start

### 1. Prerequisites
- [Telegram API credentials](https://my.telegram.org/apps) (`API_ID`, `API_HASH`).
- [Google AI Studio API Key](https://aistudio.google.com).

### 2. Setup
```bash
# Clone and enter directory
git clone <repo-url>
cd telegram-digest

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your credentials
```

### 3. Usage
```bash
# Standard run (incremental updates)
python -m src.main

# Clean run (reset database and re-summarize everything)
rm data/digest.db && python -m src.main

# Run tests
pytest
```

## 📦 Docker Deployment (Synology NAS)
The project includes a `Dockerfile` and `docker-compose.yml` optimized for Synology Container Manager.

```bash
docker-compose up --build -d
```
*Note: Ensure the `/data` directory is mounted for database and session persistence.*

## 📂 Project Structure
- `src/`: Core application logic (Client, DB, Processor, Summarizer, Reporter).
- `data/`: SQLite database, Telethon sessions, and generated Markdown reports.
- `tests/`: Comprehensive unit test suite.
- `.env.template`: Template for environment variables.

---
*Created with 💙 by Antigravity*
