# Immersive Translate Agent Design

## Goal

Add a Quasi agent that can translate a locally available PDF through Immersive Translate's Zotero-facing API, using a project-local config file and writing translated PDFs into `processing/` as disposable intermediate artifacts.

## Constraints

- The agent must not accept `auth_key` as a prompt parameter.
- Credentials must live in `config/immersive-translate.json`, aligned with existing `anna-archive.json` and `ezproxy.json` conventions.
- If the auth key is missing, the agent asks the user once, writes the config file, and only then invokes the script.
- The agent input is a generic Quasi `slug`; it should try to locate a matching PDF on its own and ask only when resolution is ambiguous or impossible.
- The default output is both bilingual and translation-only PDFs under `processing/`, not `sources/`.

## Architecture

The feature stays within Quasi's existing "thin agent, thick script" pattern. A new Python script under `scripts/translate/` owns config loading, slug resolution, request construction, upload, polling, and download. A new agent document under `agents/` explains how to gather the slug, bootstrap config, invoke the script, and recover from the two expected human-input branches: missing auth key and ambiguous source resolution.

## Data Flow

1. Agent receives a `slug`.
2. Script resolves `sources/{slug}.pdf` first, then searches common repo locations for matching PDFs.
3. Script reads `config/immersive-translate.json` and merges defaults mirroring the Zotero plugin defaults.
4. Script calls the Immersive Translate Zotero endpoints: check key, get upload URL, upload PDF, create task, poll status, fetch temporary result URLs, and download both outputs.
5. Script writes results to `processing/translations/{slug}/`.
6. Agent returns the generated file paths.

## File Plan

- Create `scripts/translate/immersive_translate.py` for the full CLI implementation.
- Create `agents/translate-agent.md` for the Quasi-facing orchestration instructions.
- Create `tests/test_immersive_translate.py` for config-path, config-default, slug-resolution, and output-path regression coverage.
- Update `README.md` to document the new agent, config file, and output location.

## Testing

- Unit tests cover pure helpers only; no live network calls.
- Verify the full Python test suite after implementation.
