#!/bin/sh
# Load missing QUASI_* configuration from Claude's encrypted macOS Keychain
# record. Values stay inside command substitution and the current process
# environment; they are never expanded into the caller's argv.

if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
    quasi_keychain_exports="$("$PLUGIN_ROOT/scripts/hooks/inject-userconfig.py" --keychain-exports)"
    if [ -n "$quasi_keychain_exports" ]; then
        eval "$quasi_keychain_exports"
    fi
    unset quasi_keychain_exports
fi
