<p align="center">
  🇬🇧 English | <a href="../SECURITY.md">🇷🇺 Русский</a>
</p>

# Security Policy

## Supported Versions

We strongly encourage all users to run the latest version of the bot to ensure stability and security. Security patches will be backported only to the current major version.

| Version  | Supported          | Note                       |
| -------- | ------------------ | -------------------------- |
| 1.25.x   | :white_check_mark: | Latest Stable Branch       |
| < 1.25.x | :x:                | End of Life (Unsupported)  |

## Reporting a Vulnerability

**DO NOT create a public GitHub Issue for security vulnerabilities.**

If you discover a security vulnerability within this project (e.g., in the Telegram Bot, WebUI, or Node monitoring script), please send an e-mail to the repository maintainers or contact them via private Telegram messages.

### What to include in your report:
* A detailed description of the vulnerability and its potential impact.
* The file(s) and line number(s) where the issue exists.
* Step-by-step instructions to reproduce the vulnerability (or a Proof of Concept script).
* The environment (e.g., Python version, OS) where the issue was observed.

### Response Timeline
We will acknowledge receipt of your vulnerability report within **48 hours**. We aim to resolve critical issues and publish a hotfix release within 7 days of confirmation.

## Security Best Practices for Deployment

To keep your bot and VPS infrastructure secure, please adhere to the following recommendations:
1. **Reverse Proxy (HTTPS):** Never run the WebUI over bare HTTP in production. Use a reverse proxy (Nginx, Caddy, or Traefik) and terminate SSL/TLS.
2. **Network Isolation:** Restrict the WebUI port (default `8080`) to `127.0.0.1` and access it only via your secure reverse proxy. Do not bind it to `0.0.0.0` without a robust firewall.
3. **Strong Credentials:** Set a complex WebUI password. The system uses Argon2 for secure hashing, but a weak password can still be brute-forced.
4. **Environment Variables:** Keep your `.env` and `config.py` files highly secure. They contain sensitive keys (Telegram Tokens, Admin IDs) that provide full access to your VPS nodes.
5. **Principle of Least Privilege:** If the bot doesn't strictly need `root` access for the specific modules you use, run it under a dedicated limited user account.

## Disclosure Policy
When a vulnerability is reported, we will coordinate with you to:
1. Confirm the issue.
2. Patch it in a private branch.
3. Release an update.
4. Credit you (if desired) in the release notes and CHANGELOG once the fix is public.
