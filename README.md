# Tuya House Smart Home Controller

Tuya House is a local FastAPI service for controlling a home full of Tuya and Smart Life devices through natural-language commands. It supports common English and Vietnamese commands, optional LLM intent parsing, and an Alexa Custom Skill integration.

## Features

- Device listing and status endpoints.
- Rule-based command parsing for common actions without an LLM.
- Optional multilingual and complex-intent parsing through the configured AI route.
- Tuya Cloud device control for lights, switches, climate devices, fans, and thermostats.
- Alexa interaction model using `AMAZON.SearchQuery` for flexible commands.
- Static local control page and a startup script with fail-closed credential checks.

## Local setup

The service listens on port 8321 by default. Configure the Tuya values in the local environment before starting:

```text
TUYA_API_KEY=[set locally]
TUYA_API_SECRET=[set locally]
```

The repository contains no real values. `start.sh` refuses to start when required credentials are missing. Do not commit device credentials, cloud tokens, tunnel URLs, or local authorization state.

## Example endpoints

```text
GET  /devices
GET  /status/{device_name}
POST /command
POST /command?use_llm=true
```

The Alexa endpoint is intended for a separately configured HTTPS endpoint. Temporary tunnel URLs are runtime values and are not stored in Git.

## Architecture

Text or voice command → FastAPI → rule parser or optional LLM parser → validated intent → Tuya Cloud API → device.

This repository is a private application source publication. It does not include a production deployment, cloud credentials, Alexa account state, or an unattended remote-control authorization.
