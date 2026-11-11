# Security Policy

## Scope

This repository contains local smart-home application source and an Alexa interaction model. It is not a credential store or device-account export.

## Never commit

- Tuya API keys, API secrets, access tokens, device credentials, or account passwords
- Alexa account credentials, OAuth files, cookies, tunnel credentials, or signed URLs
- Device inventories containing sensitive identifiers unless explicitly reviewed
- `.env` files, local databases, logs, caches, backups, or runtime state

## Safe configuration

Set Tuya and optional AI-provider values through a local secret manager or environment variables. Keep secret-bearing local files owner-readable only. Use placeholders in documentation. Review any command endpoint before exposing it beyond localhost; natural-language control can trigger real device changes.

## Pre-push checklist

- Run Python compilation and shell syntax checks.
- Run a high-confidence secret scan over staged files and reachable history.
- Confirm no device credential files, tunnel URLs, logs, or caches are staged.
- Keep the service bound locally unless the HTTPS endpoint, authentication boundary, and Alexa configuration have been reviewed.

If a secret is exposed, revoke or rotate it immediately, remove it from the current tree and reachable history, and re-scan the remote repository.
