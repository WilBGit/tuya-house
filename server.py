"""Tuya House — Natural Language Smart Home Control API.

FastAPI server that accepts natural language commands (any language),
uses an LLM to parse intent, and controls Tuya devices via the cloud API.

Also serves as an Alexa Custom Skill endpoint.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import tinytuya
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TUYA_API_KEY = os.getenv("TUYA_API_KEY", "")
TUYA_API_SECRET = os.getenv("TUYA_API_SECRET", "")
TUYA_REGION = os.environ.get("TUYA_REGION", "us")
DEVICES_JSON = os.environ.get("DEVICES_JSON", os.path.join(os.path.dirname(__file__), "..", "tuya_devices.json"))
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5.4-mini")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai-codex")
if LLM_PROVIDER == "hermes":
    LLM_PROVIDER = os.environ.get("LLM_HERMES_PROVIDER", "openai-codex")
HERMES_BIN = os.environ.get(
    "HERMES_BIN",
    "/path/to/project/.hermes/hermes-agent/.hermes/bin/hermes",
)

# Alexa skill application ID — set this when you create the skill
ALEXA_SKILL_ID = os.environ.get("ALEXA_SKILL_ID", "")

# ---------------------------------------------------------------------------
# Tuya Cloud connection
# ---------------------------------------------------------------------------
cloud = tinytuya.Cloud(
    apiRegion=TUYA_REGION,
    apiKey=TUYA_API_KEY,
    apiSecret=TUYA_API_SECRET,
    apiDeviceId="",
)

# Load device map
with open(DEVICES_JSON) as f:
    DEVICES = json.load(f)

DEVICE_MAP = {d["id"]: d for d in DEVICES}
NAME_MAP = {}
for d in DEVICES:
    key = d["name"].lower()
    NAME_MAP[key] = d
    # Also map by ID
    NAME_MAP[d["id"]] = d

# Category → human type
CATEGORY_MAP = {
    "kg": "switch",
    "dd": "light",
    "fs": "fan",
    "kt": "ac",
    "cz": "thermostat",
}

# Named colors → Tuya HSV
COLOR_MAP = {
    "red": {"h": 0, "s": 1000, "v": 1000},
    "orange": {"h": 30, "s": 1000, "v": 1000},
    "yellow": {"h": 60, "s": 1000, "v": 1000},
    "green": {"h": 120, "s": 1000, "v": 1000},
    "cyan": {"h": 180, "s": 1000, "v": 1000},
    "blue": {"h": 240, "s": 1000, "v": 1000},
    "purple": {"h": 270, "s": 1000, "v": 1000},
    "pink": {"h": 300, "s": 1000, "v": 1000},
    "magenta": {"h": 330, "s": 1000, "v": 1000},
    "white": None,  # special: set work_mode to white
    # Vietnamese color names
    "đỏ": {"h": 0, "s": 1000, "v": 1000},
    "cam": {"h": 30, "s": 1000, "v": 1000},
    "vàng": {"h": 60, "s": 1000, "v": 1000},
    "xanh lá": {"h": 120, "s": 1000, "v": 1000},
    "xanh dương": {"h": 240, "s": 1000, "v": 1000},
    "xanh": {"h": 240, "s": 1000, "v": 1000},
    "tím": {"h": 270, "s": 1000, "v": 1000},
    "hồng": {"h": 300, "s": 1000, "v": 1000},
    "trắng": None,
}

# ---------------------------------------------------------------------------
# LLM intent parser
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a smart home intent parser. Given a natural language command in ANY language, extract the intent as JSON.

Available devices:
{devices}

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "device": "<exact device name from the list>",
  "action": "<on|off|set_color|set_brightness|set_temperature|set_mode|set_fan_speed|get_status>",
  "params": {{
    // action-specific parameters
  }}
}}

Actions and their params:
- on/off: no params needed
- set_color: {{"color": "<color name or h,s,v>"}}
- set_brightness: {{"brightness": <1-100>}}  (maps to bright_value 10-1000)
- set_temperature: {{"temperature": <celsius>}}
- set_mode: {{"mode": "<auto|cold|hot|wet|wind>"}}  (AC modes)
- set_fan_speed: {{"speed": <1-5>}}
- get_status: no params

If the command is ambiguous, pick the most likely device. If you truly can't parse it, return:
{{"error": "Could not understand command"}}

Examples:
- "bật đèn Room 2" → {{"device": "Room 2", "action": "on"}}
- "đổi màu xanh" → {{"device": "Room 2", "action": "set_color", "params": {{"color": "blue"}}}}
- "make the living room cooler" → {{"device": "Living Room AC", "action": "set_temperature", "params": {{"temperature": 22}}}}
- "turn off everything in the master" → {{"device": "Master Room AC", "action": "off"}}
"""


def build_device_list() -> str:
    lines = []
    for d in DEVICES:
        cat = CATEGORY_MAP.get(d["category"], d["category"])
        lines.append(f"- {d['name']} ({cat})")
    return "\n".join(lines)


def parse_intent_llm(text: str) -> dict:
    """Use LLM to parse natural language command into structured intent."""
    prompt = SYSTEM_PROMPT.format(devices=build_device_list())
    prompt += f"\n\nUser command: {text}\n\nReturn only valid JSON."

    hermes_bin = HERMES_BIN if os.path.exists(HERMES_BIN) else (shutil.which("hermes") or HERMES_BIN)

    try:
        result = subprocess.run(
            [
                hermes_bin,
                "chat",
                "-Q",
                "--ignore-rules",
                "-t",
                "safe",
                "-q",
                prompt,
                "-m",
                LLM_MODEL,
                "--provider",
                LLM_PROVIDER,
                "--reasoning",
                "none",
                "--max-turns",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "provider process failed").strip()
            return {"error": f"LLM parse failed: Hermes provider exited {result.returncode}: {detail[:200]}"}
        content = (result.stdout or "").strip()
        if "\nsession_id:" in content:
            content = content.split("\nsession_id:", 1)[0].rstrip()
        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    except Exception as e:
        return {"error": f"LLM parse failed: {e}"}


def parse_intent_simple(text: str) -> dict:
    """Simple rule-based intent parser as fallback."""
    text_lower = text.lower().strip()

    # Find device
    device = None
    for d in DEVICES:
        if d["name"].lower() in text_lower:
            device = d
            break

    if not device:
        return {"error": f"Could not find device in: {text}"}

    name = device["name"].lower()
    action = None
    params = {}

    # On/off patterns (English + Vietnamese)
    on_words = ["on", "turn on", "bật", "mở"]
    off_words = ["off", "turn off", "tắt", "đóng"]

    for w in on_words:
        if w in text_lower:
            action = "on"
            break
    for w in off_words:
        if w in text_lower:
            action = "off"
            break

    # Color patterns
    for color_name, hsv in COLOR_MAP.items():
        if color_name in text_lower:
            action = "set_color"
            params["color"] = color_name
            break

    # Temperature patterns
    temp_match = re.search(r"(\d+)\s*°?[fc]?", text_lower)
    if temp_match and ("ac" in name or "air" in name or "nhiệt" in text_lower):
        action = "set_temperature"
        params["temperature"] = int(temp_match.group(1))

    if not action:
        return {"error": f"Could not determine action in: {text}"}

    return {"device": device["name"], "action": action, "params": params}


# ---------------------------------------------------------------------------
# Device control
# ---------------------------------------------------------------------------
def execute_command(intent: dict) -> dict:
    """Execute a parsed intent against Tuya Cloud API."""
    if "error" in intent:
        return {"success": False, "error": intent["error"]}

    device_name = intent.get("device", "")
    action = intent.get("action", "")
    params = intent.get("params", {})

    # Find device
    device = NAME_MAP.get(device_name.lower())
    if not device:
        # Fuzzy match
        for d in DEVICES:
            if device_name.lower() in d["name"].lower():
                device = d
                break
    if not device:
        return {"success": False, "error": f"Device '{device_name}' not found"}

    device_id = device["id"]
    category = device.get("category", "")
    cat_type = CATEGORY_MAP.get(category, "unknown")

    try:
        if action == "on":
            code = "switch_led" if category == "dd" else "switch"
            result = cloud.sendcommand(device_id, {"commands": [{"code": code, "value": True}]})
            return {"success": True, "device": device["name"], "action": "turned on"}

        elif action == "off":
            code = "switch_led" if category == "dd" else "switch"
            result = cloud.sendcommand(device_id, {"commands": [{"code": code, "value": False}]})
            return {"success": True, "device": device["name"], "action": "turned off"}

        elif action == "set_color":
            color_name = params.get("color", "")
            hsv = COLOR_MAP.get(color_name.lower())
            if hsv is None and color_name.lower() == "white":
                # White mode
                result = cloud.sendcommand(device_id, {
                    "commands": [
                        {"code": "work_mode", "value": "white"},
                        {"code": "bright_value", "value": 1000},
                    ]
                })
                return {"success": True, "device": device["name"], "action": f"set to white"}
            elif hsv:
                color_json = json.dumps(hsv)
                result = cloud.sendcommand(device_id, {
                    "commands": [
                        {"code": "work_mode", "value": "colour"},
                        {"code": "colour_data", "value": color_json},
                    ]
                })
                return {"success": True, "device": device["name"], "action": f"set to {color_name}"}
            else:
                # Try parsing as h,s,v
                return {"success": False, "error": f"Unknown color: {color_name}"}

        elif action == "set_brightness":
            brightness = params.get("brightness", 50)
            value = int(brightness * 10)  # 1-100 → 10-1000
            result = cloud.sendcommand(device_id, {
                "commands": [
                    {"code": "work_mode", "value": "white"},
                    {"code": "bright_value", "value": value},
                ]
            })
            return {"success": True, "device": device["name"], "action": f"brightness set to {brightness}%"}

        elif action == "set_temperature":
            temp = params.get("temperature", 72)
            result = cloud.sendcommand(device_id, {
                "commands": [{"code": "temp_set", "value": temp}]
            })
            return {"success": True, "device": device["name"], "action": f"temperature set to {temp}°"}

        elif action == "set_mode":
            mode = params.get("mode", "auto")
            result = cloud.sendcommand(device_id, {
                "commands": [{"code": "mode", "value": mode}]
            })
            return {"success": True, "device": device["name"], "action": f"mode set to {mode}"}

        elif action == "set_fan_speed":
            speed = params.get("speed", 3)
            result = cloud.sendcommand(device_id, {
                "commands": [{"code": "fan_speed_percent", "value": speed}]
            })
            return {"success": True, "device": device["name"], "action": f"fan speed set to {speed}"}

        elif action == "get_status":
            status = cloud.getstatus(device_id)
            return {"success": True, "device": device["name"], "status": status}

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Alexa response helpers
# ---------------------------------------------------------------------------
def alexa_speech(text: str, end_session: bool = True) -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": text,
            },
            "shouldEndSession": end_session,
        },
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Tuya House", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve web UI
from fastapi.staticfiles import StaticFiles
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/ui")
async def ui():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/")
def root():
    return {
        "service": "Tuya House",
        "devices": len(DEVICES),
        "endpoints": ["/command", "/status", "/alexa", "/devices"],
    }


@app.get("/devices")
def list_devices():
    return [
        {
            "name": d["name"],
            "id": d["id"],
            "type": CATEGORY_MAP.get(d["category"], d["category"]),
            "product": d.get("product_name", ""),
        }
        for d in DEVICES
    ]


@app.get("/status/{device_name:path}")
def get_status(device_name: str):
    device = NAME_MAP.get(device_name.lower())
    if not device:
        for d in DEVICES:
            if device_name.lower() in d["name"].lower():
                device = d
                break
    if not device:
        return {"error": f"Device '{device_name}' not found"}
    try:
        status = cloud.getstatus(device["id"])
        return {"device": device["name"], "status": status}
    except Exception as e:
        return {"error": str(e)}


@app.post("/command")
async def command(request: Request):
    """Natural language command endpoint.

    Body: {"text": "bật đèn Room 2"} or {"text": "make the living room cooler"}
    Query: ?use_llm=true to force LLM parsing
    """
    body = await request.json()
    text = body.get("text", "").strip()
    use_llm = body.get("use_llm", False) or request.query_params.get("use_llm", "").lower() == "true"

    if not text:
        return {"error": "Missing 'text' field"}

    # Try simple parser first, fall back to LLM
    intent = parse_intent_simple(text)
    if "error" in intent or use_llm:
        intent = parse_intent_llm(text)

    result = execute_command(intent)
    return {"intent": intent, "result": result}


@app.post("/alexa")
async def alexa_endpoint(request: Request):
    """Alexa Custom Skill endpoint.

    Handles LaunchRequest, IntentRequest, and SessionEndedRequest.
    The custom skill uses AMAZON.SearchQuery slot to capture raw utterances.
    """
    body = await request.json()

    # Verify application ID if configured
    session = body.get("session", {})
    app_id = session.get("application", {}).get("applicationId", "")
    if ALEXA_SKILL_ID and app_id != ALEXA_SKILL_ID:
        return JSONResponse(status_code=403, content={"error": "Invalid application ID"})

    request_type = body.get("request", {}).get("type", "")

    # LaunchRequest — user said "Alexa, open <skill name>"
    if request_type == "LaunchRequest":
        return alexa_speech(
            "Tuya House is ready. What would you like to do?",
            end_session=False,
        )

    # IntentRequest
    if request_type == "IntentRequest":
        intent_obj = body["request"]["intent"]
        intent_name = intent_obj.get("name", "")
        slots = intent_obj.get("slots", {})

        # Handle AMAZON.StopIntent / CancelIntent
        if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return alexa_speech("Goodbye!")

        # Handle HelpIntent
        if intent_name == "AMAZON.HelpIntent":
            return alexa_speech(
                "You can say things like: turn on Room 2, or set the living room AC to 72 degrees. "
                "I understand English, Vietnamese, and other languages.",
                end_session=False,
            )

        # Our custom intent: ControlHouse with a SearchQuery slot
        utterance = slots.get("Command", {}).get("value", "")
        if not utterance:
            return alexa_speech("I didn't catch that. Try saying a command like turn on Room 2.")

        # Parse and execute
        intent = parse_intent_simple(utterance)
        if "error" in intent:
            intent = parse_intent_llm(utterance)

        result = execute_command(intent)

        if result.get("success"):
            response_text = result.get("action", "Done!")
            # Make it more conversational
            device = result.get("device", "")
            if device:
                response_text = f"{device} {response_text}"
        else:
            response_text = f"Sorry, I couldn't do that. {result.get('error', 'Unknown error')}"

        return alexa_speech(response_text)

    # SessionEndedRequest
    return alexa_speech("")


@app.post("/alexa/skill")
async def alexa_skill_alias(request: Request):
    """Alias for /alexa — some Alexa configs use this path."""
    return await alexa_endpoint(request)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8321))
    uvicorn.run(app, host="0.0.0.0", port=port)
