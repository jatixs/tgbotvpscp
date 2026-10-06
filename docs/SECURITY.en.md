<p align="center">
  <img src="https://flagcdn.com/20x15/gb.png" width="16" alt="EN"> English | <a href="../SECURITY.md"><img src="https://flagcdn.com/20x15/ru.png" width="16" alt="RU"> Русский</a>
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
6. **Canonical URL:** Set `WEB_PUBLIC_URL` to the panel's full HTTPS origin, for example `https://panel.example.com` or `https://panel.example.com:8443`. Magic login, password reset, and node provisioning are disabled unless this URL is valid.
7. **HTTPS without a domain:** managed TLS supports globally routable public IPv4 addresses using a short-lived Let's Encrypt IP certificate (160 hours). Inbound TCP port 80 must remain reachable for HTTP-01; renewal is checked hourly. Private IPv4 addresses are not supported. For an external reverse proxy, set its HTTPS origin as `WEB_PUBLIC_URL` and configure certificate issuance and renewal there.
8. **Upgrade existing installations:** update the master with the installer first, then update node agents. The legacy HTTP bridge is limited to discovery, bootstrap, and HMAC-protected heartbeat; an updated agent validates the HTTPS endpoint and persists its new URL. Run `tgcp-bot tls status`, then `tgcp-bot tls finalize` once every node is confirmed to disable the bridge. Rotate old node tokens afterward: previous versions could expose them to signed-in WebUI users. The old `admin` password is no longer accepted; sign in through Telegram and set a new password.
9. **Docker secure profile:** container mutations are intentionally available only in the root profile; the secure profile can read container status but has no write access to the Docker API.

## Disclosure Policy
When a vulnerability is reported, we will coordinate with you to:
1. Confirm the issue.
2. Patch it in a private branch.
3. Release an update.
4. Credit you (if desired) in the release notes and CHANGELOG once the fix is public.
