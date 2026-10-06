<p align="center">
  <img src="https://flagcdn.com/20x15/gb.png" width="16" alt="EN"> English | <a href="../CONTRIBUTING.md"><img src="https://flagcdn.com/20x15/ru.png" width="16" alt="RU"> Русский</a>
</p>

# Contributing to Telegram VPS Management Bot

Welcome! We love your input! We want to make contributing to this project as easy and transparent as possible, whether it's:
- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Architecture & Tech Stack

This project is divided into several logical components:
* **Bot Core (`bot.py`, `core/`)**: Built on `aiogram 3.x` for Telegram bot interactions.
* **WebUI (`core/web/`, `core/static/`)**: Built with `aiohttp` and `Jinja2` templates. Frontend styling uses TailwindCSS and vanilla JS.
* **Database**: `tortoise-orm` with SQLite through `aiosqlite`.
* **VPS Node Agent (`node/`)**: Lightweight monitoring agent installed on remote VPS nodes, communicating with the main bot.

### Project Structure
* `core/`: Core functionality, Web API, i18n, configs, and middlewares.
* `modules/`: Feature-specific modules (like selftest, billing, services monitoring).
* `node/`: The node script installed on managed VPS.
* `watchdog.py`: Auto-restart and self-healing daemon.
* `manage.py`: CLI for database migrations and administration.

## Development Setup

1. **Prerequisites**: Python 3.10 or higher.
2. **Clone the repository**:
   ```bash
   git clone https://github.com/jatixs/tgbotvpscp.git
   cd tgbotvpscp
   ```
3. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```
4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Configuration**:
   Never put production secrets in a development checkout. Create a local `.env` using the variables read by `core/config.py`; the repository does not include `.env.example`. Use a dedicated test bot and isolated test data.
6. **Run the bot**:
   ```bash
   python bot.py
   ```

## Development Guidelines

### Code Style
- We follow **PEP 8** standards.
- We use **Ruff** for linting. Please ensure your code passes checks before submitting:
  ```bash
   ruff check .
  ```
- Use Python type hinting wherever possible (e.g., `def handler(message: types.Message) -> None:`).

### Committing Changes
We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
- `feat(web): add dark mode toggle` for new features.
- `fix(core): resolve null pointer exception` for bug fixes.
- `docs: update readme` for documentation.
- `style: auto-fix safe ruff linting errors` for formatting/linting changes.

### Pull Requests
1. Fork the repo and create your branch from `main`.
2. Name your branch logically: `feature/your-feature-name` or `bugfix/issue-number`.
3. Run the relevant checks: `python -m unittest discover -s tests`; for installers, run `bash -n deploy.sh` and `bash -n deploy_en.sh` in Linux/macOS or Git Bash.
4. Update `CHANGELOG.md`; for auth, node-protocol, or deployment changes, synchronize the Russian and English docs and security guidance.
5. Open a Pull Request!

## Translations (i18n)
All text constants and interface translations are located in `core/i18n.py`. If you are adding new UI text, please define it in the i18n dictionaries for both English (`en`) and Russian (`ru`), rather than hardcoding it into the HTML or Python strings.
