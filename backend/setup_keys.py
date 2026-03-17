#!/usr/bin/env python3
"""Interactive setup for Voxyflow API keys.
Stores keys securely in the OS keyring (cross-platform).
"""
import keyring
import getpass
import sys

SERVICE = "voxyflow"

KEYS = {
    "claude_api_key": {
        "prompt": "Anthropic Claude API Key (sk-ant-...)",
        "required": True,
    },
}


def setup():
    print("=" * 50)
    print("  Voxyflow — Secure Key Setup")
    print("=" * 50)
    print()
    print("Keys are stored in your OS keyring:")
    print("  Linux: GNOME Keyring / KWallet / Secret Service")
    print("  macOS: Keychain")
    print("  Windows: Credential Manager")
    print()

    for key_name, config in KEYS.items():
        existing = keyring.get_password(SERVICE, key_name)
        if existing:
            masked = existing[:10] + "..." + existing[-4:]
            print(f"  {key_name}: {masked} (already set)")
            change = input(f"  Change {key_name}? [y/N]: ").strip().lower()
            if change != "y":
                continue

        value = getpass.getpass(f"  Enter {config['prompt']}: ")
        if not value and config.get("required"):
            print(f"  ⚠️  {key_name} is required. Skipping.")
            continue

        keyring.set_password(SERVICE, key_name, value)
        print(f"  ✅ {key_name} stored securely.")

    print()
    print("Done! Keys are now available to Voxyflow.")
    print("Run: python -m uvicorn app.main:app --reload")


def show():
    """Show which keys are set (masked)."""
    print("Voxyflow stored keys:")
    for key_name in KEYS:
        val = keyring.get_password(SERVICE, key_name)
        if val:
            masked = val[:10] + "..." + val[-4:]
            print(f"  ✅ {key_name}: {masked}")
        else:
            print(f"  ❌ {key_name}: NOT SET")


def clear():
    """Remove all stored keys."""
    for key_name in KEYS:
        try:
            keyring.delete_password(SERVICE, key_name)
            print(f"  🗑️  {key_name} removed.")
        except keyring.errors.PasswordDeleteError:
            print(f"  ⚠️  {key_name} was not set.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "show":
            show()
        elif sys.argv[1] == "clear":
            clear()
        else:
            print("Usage: python setup_keys.py [show|clear]")
    else:
        setup()
