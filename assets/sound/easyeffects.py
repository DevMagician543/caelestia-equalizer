#!/usr/bin/env python3
"""Small, bounded client for EasyEffects 8.3's local control socket."""
import json
import math
import os
from pathlib import Path
import shutil
import socket
import sys

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCKET = os.path.join(RUNTIME, "EasyEffectsServer")
BASE = "output:equalizer:0"


def plugin_status():
    """The socket exposes settings even when the LV2 processor failed to load."""
    paths = os.environ.get("LV2_PATH", "").split(":")
    paths += ["/usr/lib/lv2", "/usr/lib64/lv2", "/usr/local/lib/lv2",
              str(Path.home() / ".lv2")]
    bundles = [Path(path) / "lsp-plugins.lv2" for path in paths if path]
    if not any((bundle / "para_equalizer_x32_lr.ttl").exists() and
               (bundle / "lsp-plugins-lv2.so").exists() for bundle in bundles):
        return "Equalizer audio plugin missing: install lsp-plugins-lv2"
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() != "easyeffects":
                continue
            if "lsp-plugins-lv2.so" in (process / "maps").read_text():
                return None
        except (OSError, UnicodeError):
            continue
    return "Equalizer audio plugin is not loaded; restart EasyEffects"


def request(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.7)
        client.connect(SOCKET)
        client.sendall((command + "\n").encode())
        if not command.startswith("get_"):
            return None
        data = b""
        while len(data) < 256:
            chunk = client.recv(256)
            if not chunk:
                break
            data += chunk
            if b"\n" in data or command == "get_global_bypass":
                break
        result = data.decode().strip()
        if not result or result.startswith("error_"):
            raise ValueError(result or "No response from EasyEffects")
        return result


def prop(name, channel=None):
    target = BASE + (":" + channel if channel else "")
    return request("get_property:" + target + ":" + name)


def set_prop(name, value, channel=None):
    target = BASE + (":" + channel if channel else "")
    encoded = str(value).lower() if isinstance(value, bool) else str(value)
    request("set_property:" + target + ":" + name + ":" + encoded)
    result = prop(name, channel)
    if isinstance(value, bool):
        success = result.lower() in ("true", "1") if value else result.lower() in ("false", "0")
    else:
        success = math.isclose(float(result), float(value), abs_tol=0.06)
    if not success:
        raise ValueError(f"EasyEffects did not apply {name}: {result}")


def snapshot():
    if not shutil.which("easyeffects"):
        return {"status": "EasyEffects is not installed", "ready": False}
    if not os.path.exists(SOCKET):
        return {"status": "EasyEffects is not running", "ready": False}
    try:
        count = int(prop("numBands"))
        if count < 1 or count > 32:
            raise ValueError("Unsupported equalizer band count")
        missing_plugin = plugin_status()
        if missing_plugin:
            return {"ready": False, "status": missing_plugin}
        bands = []
        for i in range(count):
            bands.append({"frequency": float(prop(f"band{i}Frequency", "left")),
                          "gain": float(prop(f"band{i}Gain", "left"))})
        bypass = prop("bypass").lower() in ("true", "1")
        global_bypass = request("get_global_bypass") == "1"
        return {"ready": True, "status": "Equalizer bypassed" if bypass else
                "EasyEffects globally bypassed" if global_bypass else "Equalizer available",
                "bands": bands, "bypass": bypass, "globalBypass": global_bypass,
                "splitChannels": prop("splitChannels").lower() in ("true", "1")}
    except ValueError as exc:
        if str(exc) == "error_plugin_not_found":
            return {"ready": False, "status": "No equalizer in the EasyEffects output chain"}
        return {"ready": False, "status": "Equalizer unavailable: " + str(exc)}
    except OSError as exc:
        return {"ready": False, "status": "EasyEffects is not responding: " + str(exc)}


def main():
    action = sys.argv[1]
    if action == "snapshot":
        print(json.dumps(snapshot()))
        return
    before = snapshot()
    if not before["ready"]:
        print(json.dumps(before))
        return
    try:
        if action == "gain":
            index, gain = int(sys.argv[2]), float(sys.argv[3])
            if index < 0 or index >= len(before["bands"]) or not -12 <= gain <= 12:
                raise ValueError("Band or gain out of range")
            for channel in ("left", "right"):
                set_prop(f"band{index}Gain", gain, channel)
        elif action == "preset":
            values = json.loads(sys.argv[2])
            if len(values) != len(before["bands"]) or any(not isinstance(v, (float, int)) or not -12 <= v <= 12 for v in values):
                raise ValueError("Invalid preset values")
            for index, gain in enumerate(values):
                for channel in ("left", "right"):
                    set_prop(f"band{index}Gain", gain, channel)
        elif action == "enabled":
            set_prop("bypass", sys.argv[2] != "true")
        else:
            raise ValueError("Unknown action")
        print(json.dumps(snapshot()))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ready": False, "status": "Update failed: " + str(exc)}))


if __name__ == "__main__":
    main()
