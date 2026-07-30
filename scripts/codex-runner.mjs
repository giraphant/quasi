#!/usr/bin/env node

import { spawn } from "node:child_process";
import {
	mkdir,
	mkdtemp,
	readFile,
	rm,
	writeFile,
} from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createRunner } from "./pi-runner.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_PLUGIN_ROOT = resolve(HERE, "..");
const DEFAULT_TIMEOUT_MS = 45 * 60 * 1000;
const SHELL_ENV_ALLOWLIST = [
	"PATH",
	"HOME",
	"TMPDIR",
	"TMP",
	"TEMP",
	"SHELL",
	"LANG",
	"LC_*",
	"USER",
	"LOGNAME",
	"PWD",
	"SSH_AUTH_SOCK",
	"QUASI_*",
	"CLAUDE_PROJECT_DIR",
	"CLAUDE_PLUGIN_ROOT",
	"CLAUDE_PLUGIN_DATA",
	"PLUGIN_ROOT",
	"PLUGIN_DATA",
	"UV_*",
	"XDG_*",
];

function parseJson(text, source) {
	try {
		return JSON.parse(text);
	} catch (error) {
		throw new Error(`invalid JSON in ${source}: ${error.message}`);
	}
}

function nullable(schema) {
	if (Array.isArray(schema.type)) {
		return schema.type.includes("null")
			? schema
			: { ...schema, type: [...schema.type, "null"] };
	}
	if (typeof schema.type === "string")
		return { ...schema, type: [schema.type, "null"] };
	return { anyOf: [schema, { type: "null" }] };
}

function strictProperty(schema, required) {
	const strict = strictSchema(schema);
	return required ? strict : nullable(strict);
}

/**
 * Codex structured outputs use strict JSON Schema: object properties must be
 * closed and every property must be required. The Claude Workflow schemas use
 * ordinary optional properties, so make those properties nullable without
 * changing the graph-facing result shape.
 */
export function strictSchema(schema) {
	if (!schema || typeof schema !== "object" || Array.isArray(schema))
		throw new Error("output schema must be a JSON object");
	if (!Object.keys(schema).length)
		return {
			anyOf: [
				{ type: "string" },
				{ type: "number" },
				{ type: "boolean" },
				{ type: "null" },
			],
		};

	const output = { ...schema };
	const outputTypes = Array.isArray(output.type)
		? output.type
		: output.type
			? [output.type]
			: [];
	if (
		outputTypes.includes("object") ||
		(!output.type && output.properties && typeof output.properties === "object")
	) {
		const properties = output.properties || {};
		const originallyRequired = new Set(output.required || []);
		if (!output.type) output.type = "object";
		output.properties = Object.fromEntries(
			Object.entries(properties).map(([name, child]) => [
				name,
				strictProperty(child, originallyRequired.has(name)),
			]),
		);
		output.required = Object.keys(properties);
		output.additionalProperties = false;
	}
	if (outputTypes.includes("array") && output.items)
		output.items = strictSchema(output.items);
	if (Array.isArray(output.anyOf))
		output.anyOf = output.anyOf.map((child) => strictSchema(child));
	return output;
}

function trimDiagnostic(text, limit = 6000) {
	if (text.length <= limit) return text;
	return text.slice(text.length - limit);
}

function runCodex(command, argv, prompt, { cwd, env, signal }) {
	return new Promise((resolveRun, rejectRun) => {
		const child = spawn(command, argv, {
			cwd,
			env,
			stdio: ["pipe", "pipe", "pipe"],
		});
		let stdout = "";
		let stderr = "";
		const append = (current, chunk) =>
			trimDiagnostic(current + chunk.toString(), 200_000);
		child.stdout.on("data", (chunk) => {
			stdout = append(stdout, chunk);
		});
		child.stderr.on("data", (chunk) => {
			stderr = append(stderr, chunk);
		});

		const abort = () => child.kill("SIGTERM");
		if (signal?.aborted) abort();
		signal?.addEventListener("abort", abort, { once: true });
		child.once("error", rejectRun);
		child.once("close", (code, childSignal) => {
			signal?.removeEventListener("abort", abort);
			if (code === 0) {
				resolveRun({ stdout, stderr });
				return;
			}
			rejectRun(
				new Error(
					`codex exec exited ${code ?? childSignal}: ${trimDiagnostic(
						stderr || stdout,
					)}`,
				),
			);
		});
		child.stdin.end(prompt);
	});
}

function runtimeInstructions(definition, projectCwd, pluginRoot, hasSchema) {
	const capabilities = definition.piTools.length
		? definition.piTools.join(", ")
		: "no local tools";
	return `${definition.body}

Runtime contract:
- Work in ${projectCwd}.
- Quasi plugin code is at ${pluginRoot}; treat it as read-only.
- The workflow graph, not this worker, owns orchestration. Do not spawn subagents.
- Declared capabilities for this worker: ${capabilities}.
- Do not use web or network retrieval unless the assigned contract requires it.
- Follow the assigned output path exactly and do not write any other product.
${
	hasSchema
		? "- Your final response must be only the JSON receipt requested by the output schema."
		: "- Return only the concise result requested by the caller."
}`;
}

export function createCodexInvoker({
	projectCwd,
	pluginRoot,
	command = process.env.QUASI_CODEX_BIN || "codex",
	log = () => {},
} = {}) {
	const cwd = resolve(projectCwd || process.cwd());
	const root = resolve(pluginRoot || DEFAULT_PLUGIN_ROOT);
	return async ({ definition, prompt, options, signal }) => {
		const tempRoot = join(cwd, ".quasi", "temp");
		await mkdir(tempRoot, { recursive: true });
		const workDir = await mkdtemp(join(tempRoot, "codex-agent-"));
		const outputPath = join(workDir, "last-message.json");
		const argv = [
			"exec",
			"--ephemeral",
			"--ignore-user-config",
			"--skip-git-repo-check",
			"--color",
			"never",
			"--sandbox",
			"workspace-write",
			"--cd",
			cwd,
			"--output-last-message",
			outputPath,
			"--config",
			"sandbox_workspace_write.network_access=true",
			"--config",
			"shell_environment_policy.inherit=\"all\"",
			"--config",
			"shell_environment_policy.ignore_default_excludes=true",
			"--config",
			`shell_environment_policy.include_only=${JSON.stringify(
				SHELL_ENV_ALLOWLIST,
			)}`,
		];

		const pluginData =
			process.env.PLUGIN_DATA || process.env.CLAUDE_PLUGIN_DATA;
		if (pluginData) argv.push("--add-dir", resolve(pluginData));
		if (process.env.QUASI_CODEX_MODEL)
			argv.push("--model", process.env.QUASI_CODEX_MODEL);
		const reasoning =
			process.env.QUASI_CODEX_REASONING_LEVEL ||
			(definition.model === "opus"
				? "high"
				: definition.model === "sonnet"
					? "medium"
					: "low");
		argv.push(
			"--config",
			`model_reasoning_effort=${JSON.stringify(reasoning)}`,
		);

		if (options.schema) {
			const schemaPath = join(workDir, "schema.json");
			await writeFile(
				schemaPath,
				`${JSON.stringify(strictSchema(options.schema), null, 2)}\n`,
			);
			argv.push("--output-schema", schemaPath);
		}
		argv.push(
			"--config",
			`developer_instructions=${JSON.stringify(
				runtimeInstructions(
					definition,
					cwd,
					root,
					Boolean(options.schema),
				),
			)}`,
			"-",
		);

		log(`agent ${options.label || definition.name}: starting Codex worker`);
		try {
			await runCodex(command, argv, prompt, {
				cwd,
				env: process.env,
				signal,
			});
			const final = (await readFile(outputPath, "utf8")).trim();
			if (!final)
				throw new Error(
					`Codex worker ${options.label || definition.name} returned no final message`,
				);
			return options.schema
				? parseJson(final, `${options.label || definition.name} receipt`)
				: final;
		} catch (error) {
			log(`agent ${options.label || definition.name} failed: ${error.message}`);
			return null;
		} finally {
			await rm(workDir, { recursive: true, force: true });
		}
	};
}

function parseCli(argv) {
	const options = {};
	for (let i = 0; i < argv.length; i++) {
		const flag = argv[i];
		if (!flag.startsWith("--")) throw new Error(`unexpected argument: ${flag}`);
		const value = argv[++i];
		if (value === undefined) throw new Error(`missing value for ${flag}`);
		options[flag.slice(2)] = value;
	}
	return options;
}

async function main() {
	const cli = parseCli(process.argv.slice(2));
	const pluginRoot = resolve(cli["plugin-root"] || DEFAULT_PLUGIN_ROOT);
	const script = resolve(
		cli.script ||
			join(pluginRoot, "workflows", "process-material.mjs"),
	);
	const projectCwd = resolve(
		cli.cwd || process.env.CLAUDE_PROJECT_DIR || process.cwd(),
	);
	const argsPath = cli["args-file"] && resolve(cli["args-file"]);
	const args = argsPath
		? parseJson(await readFile(argsPath, "utf8"), argsPath)
		: parseJson(cli["args-json"] || "{}", "--args-json");
	const controller = new AbortController();
	process.once("SIGINT", () => controller.abort());
	process.once("SIGTERM", () => controller.abort());
	const log = (message) => process.stderr.write(`[quasi-codex] ${message}\n`);
	const runner = createRunner({
		pluginRoot,
		projectCwd,
		concurrency: Number(cli.concurrency || 4),
		timeoutMs: Number(cli["timeout-ms"] || DEFAULT_TIMEOUT_MS),
		signal: controller.signal,
		log,
		invokeAgent: createCodexInvoker({ projectCwd, pluginRoot, log }),
	});
	const result = await runner.runFile(script, args);
	process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
	main().catch((error) => {
		process.stderr.write(`[quasi-codex] ${error.stack || error.message}\n`);
		process.exitCode = 1;
	});
}
