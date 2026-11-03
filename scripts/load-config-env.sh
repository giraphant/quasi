#!/bin/sh
# Fill missing QUASI_* values from quasi's macOS Keychain items
# (scripts/config/config.py). Values stay inside command substitution and this
# process's environment; they never reach argv. Explicit QUASI_* values win.

if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
    quasi_config_exports="$(python3 -I "$PLUGIN_ROOT/scripts/config/config.py" exports)" || quasi_config_exports=""
    if [ -n "$quasi_config_exports" ]; then
        eval "$quasi_config_exports"
    fi
    unset quasi_config_exports
fi
