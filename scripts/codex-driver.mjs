#!/usr/bin/env node

import {
	mkdir,
	mkdtemp,
	readFile,
	rm,
	writeFile,
} from "node:fs/promises";
import { createInterface } from "node:readline";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createRunner } from "./pi-runner.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_PLUGIN_ROOT = resolve(HERE, "..");
const DEFAULT_TIMEOUT_MS = 45 * 60 * 1000;
const PROTOCOL = "quasi-codex-driver/1";
const USAGE =
	"Usage: quasi-codex-driver [--script PATH] [--args-file JSON|--args-json JSON] " +
	"[--cwd PROJECT] [--concurrency N] [--timeout-ms N]\n";

function codexAgentType(agentType) {
	if (!agentType || agentType === "general-purpose") return "worker";
	const match = agentType.match(/^quasi:([a-z0-9-]+?)(?:-agent)?$/);
	return match ? `quasi_${match[1].replace(/-/g, "_")}` : "worker";
}

function parseJson(text, source) {
	try {
		return JSON.parse(text);
	} catch (error) {
		throw new Error(`invalid JSON in ${source}: ${error.message}`);
	}
}

function receiptFrom(value) {
	if (typeof value !== "string") return value;
	const trimmed = value.trim();
	const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
	return parseJson(fenced ? fenced[1] : trimmed, "agent_result.result");
}

function matchesType(value, type) {
	if (type === "null") return value === null;
	if (type === "array") return Array.isArray(value);
	if (type === "object")
		return value !== null && typeof value === "object" && !Array.isArray(value);
	if (type === "integer") return Number.isInteger(value);
	if (type === "number") return typeof value === "number" && Number.isFinite(value);
	return typeof value === type;
}

function validateReceipt(value, schema, path = "$") {
	if (!schema || typeof schema !== "object" || !Object.keys(schema).length) return;
	if (Array.isArray(schema.anyOf)) {
		const errors = [];
		for (const option of schema.anyOf) {
			try {
				validateReceipt(value, option, path);
				return;
			} catch (error) {
				errors.push(error.message);
			}
		}
		throw new Error(`${path} did not match anyOf: ${errors.join("; ")}`);
	}
	if (
		Object.prototype.hasOwnProperty.call(schema, "const") &&
		!Object.is(schema.const, value)
	)
		throw new Error(`${path} must equal ${JSON.stringify(schema.const)}`);
	if (schema.enum && !schema.enum.some((item) => Object.is(item, value)))
		throw new Error(`${path} must be one of ${JSON.stringify(schema.enum)}`);
	const types = Array.isArray(schema.type)
		? schema.type
		: schema.type
			? [schema.type]
			: [];
	if (types.length && !types.some((type) => matchesType(value, type)))
		throw new Error(`${path} must have type ${types.join("|")}`);
	if (value === null) return;
	if (typeof value === "string") {
		if (Number.isInteger(schema.minLength) && value.length < schema.minLength)
			throw new Error(`${path} must have length >= ${schema.minLength}`);
		if (Number.isInteger(schema.maxLength) && value.length > schema.maxLength)
			throw new Error(`${path} must have length <= ${schema.maxLength}`);
		if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value))
			throw new Error(`${path} must match ${schema.pattern}`);
	}
	if (typeof value === "number" && Number.isFinite(value)) {
		if (typeof schema.minimum === "number" && value < schema.minimum)
			throw new Error(`${path} must be >= ${schema.minimum}`);
		if (typeof schema.maximum === "number" && value > schema.maximum)
			throw new Error(`${path} must be <= ${schema.maximum}`);
	}
	if (
		(schema.type === "object" || schema.properties) &&
		value &&
		typeof value === "object" &&
		!Array.isArray(value)
	) {
		for (const name of schema.required || []) {
			if (!(name in value)) throw new Error(`${path}.${name} is required`);
		}
		for (const [name, child] of Object.entries(schema.properties || {})) {
			if (name in value) validateReceipt(value[name], child, `${path}.${name}`);
		}
		if (schema.additionalProperties === false) {
			const allowed = new Set(Object.keys(schema.properties || {}));
			for (const name of Object.keys(value)) {
				if (!allowed.has(name))
					throw new Error(`${path}.${name} is not allowed`);
			}
		}
	}
	if (Array.isArray(value) && schema.items) {
		if (Number.isInteger(schema.minItems) && value.length < schema.minItems)
			throw new Error(`${path} must contain at least ${schema.minItems} items`);
		if (Number.isInteger(schema.maxItems) && value.length > schema.maxItems)
			throw new Error(`${path} must contain at most ${schema.maxItems} items`);
		value.forEach((item, index) =>
			validateReceipt(item, schema.items, `${path}[${index}]`),
		);
	}
}

function createEmitter(stream = process.stdout) {
	let tail = Promise.resolve();
	return {
		emit(event) {
			const line = `${JSON.stringify(event)}\n`;
			tail = tail.then(
				() =>
					new Promise((resolveWrite, rejectWrite) => {
						stream.write(line, (error) =>
							error ? rejectWrite(error) : resolveWrite(),
						);
					}),
			);
			return tail;
		},
		flush: () => tail,
	};
}

export function createAgentBridge({
	emit,
	requestDir,
	pluginRoot = DEFAULT_PLUGIN_ROOT,
	projectCwd = process.cwd(),
}) {
	let sequence = 0;
	const pending = new Map();

	function settle(id, value) {
		const request = pending.get(id);
		if (!request) return false;
		pending.delete(id);
		request.signal?.removeEventListener("abort", request.abort);
		request.resolve(value);
		return true;
	}

	async function invoke({ definition, prompt, options, signal }) {
		const id = `agent-${++sequence}`;
		const agentType = options.agentType || "general-purpose";
		const nativeAgentType = codexAgentType(agentType);
		const requestPath = join(requestDir, `${id}.json`);
		const receiptPath = join(requestDir, `${id}.receipt.json`);
		await writeFile(
			requestPath,
			`${JSON.stringify(
				{
					protocol: PROTOCOL,
					id,
					agent_type: agentType,
					codex_agent_type: nativeAgentType,
					name: definition.name,
					label: options.label || definition.name,
					model_hint: definition.model,
					capabilities: definition.piTools,
					plugin_root: pluginRoot,
					project_cwd: projectCwd,
					receipt_path: receiptPath,
					instructions: definition.body,
					prompt,
					schema: options.schema || null,
				},
				null,
				2,
			)}\n`,
		);
		return new Promise((resolveRequest) => {
			const abort = () => {
				if (!settle(id, null)) return;
				void emit({
					type: "agent_cancel",
					id,
					label: options.label || definition.name,
					reason: "timeout_or_abort",
				});
			};
			pending.set(id, {
				resolve: resolveRequest,
				signal,
				abort,
				schema: options.schema,
				requestPath,
				receiptPath,
			});
			signal?.addEventListener("abort", abort, { once: true });
			if (signal?.aborted) {
				abort();
				return;
			}
			void emit({
				type: "agent_request",
				id,
				agent_type: agentType,
				codex_agent_type: nativeAgentType,
				name: definition.name,
				label: options.label || definition.name,
				model_hint: definition.model,
				capabilities: definition.piTools,
				request_path: requestPath,
				receipt_path: receiptPath,
			}).catch(() => settle(id, null));
		});
	}

	async function handle(message) {
		if (message.type === "agent_result") {
			const request = pending.get(message.id);
			if (!request)
				return emit({
					type: "protocol_error",
					id: message.id,
					error: "unknown or already-settled agent request",
				});
			try {
				let wireResult = message.result;
				if (message.result_path !== undefined) {
					if (resolve(message.result_path) !== resolve(request.receiptPath))
						throw new Error(
							`result_path must match assigned receipt_path: ${request.receiptPath}`,
						);
					wireResult = parseJson(
						await readFile(request.receiptPath, "utf8"),
						request.receiptPath,
					);
				}
				const result = request.schema
					? receiptFrom(wireResult)
					: wireResult;
				if (request.schema) validateReceipt(result, request.schema);
				settle(message.id, result);
			} catch (error) {
				await emit({
					type: "receipt_rejected",
					id: message.id,
					error: error.message,
					request_path: request.requestPath,
					receipt_path: request.receiptPath,
				});
			}
			return;
		}
		if (message.type === "agent_error") {
			if (!settle(message.id, null))
				await emit({
					type: "protocol_error",
					id: message.id,
					error: "unknown or already-settled agent request",
				});
			return;
		}
		if (message.type === "ping") {
			await emit({ type: "pong" });
			return;
		}
		await emit({
			type: "protocol_error",
			error: `unsupported input event: ${message.type || "<missing>"}`,
		});
	}

	function close() {
		for (const id of [...pending.keys()]) settle(id, null);
	}

	return {
		invoke,
		handle,
		close,
		pendingCount: () => pending.size,
	};
}

function parseCli(argv) {
	const options = {};
	for (let i = 0; i < argv.length; i++) {
		const flag = argv[i];
		if (!flag.startsWith("--")) throw new Error(`unexpected argument: ${flag}`);
		if (flag === "--help") {
			options.help = true;
			continue;
		}
		const value = argv[++i];
		if (value === undefined) throw new Error(`missing value for ${flag}`);
		options[flag.slice(2)] = value;
	}
	return options;
}

async function main() {
	const cli = parseCli(process.argv.slice(2));
	if (cli.help) {
		process.stdout.write(USAGE);
		return;
	}
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
	const concurrency = Number(cli.concurrency || 3);
	const timeoutMs = Number(cli["timeout-ms"] || DEFAULT_TIMEOUT_MS);
	const controller = new AbortController();
	const output = createEmitter();
	const tempRoot = join(projectCwd, ".quasi", "temp");
	await mkdir(tempRoot, { recursive: true });
	const requestDir = await mkdtemp(join(tempRoot, "codex-driver-"));
	const bridge = createAgentBridge({
		emit: output.emit,
		requestDir,
		pluginRoot,
		projectCwd,
	});
	const rawInput = Boolean(process.stdin.isTTY && process.stdin.setRawMode);
	if (rawInput) process.stdin.setRawMode(true);
	const input = createInterface({ input: process.stdin, crlfDelay: Infinity });

	input.on("line", (line) => {
		if (!line.trim()) return;
		let message;
		try {
			message = parseJson(line, "stdin");
		} catch (error) {
			void output.emit({ type: "protocol_error", error: error.message });
			return;
		}
		if (message.type === "cancel") {
			controller.abort();
			return;
		}
		void bridge.handle(message);
	});
	input.on("close", () => {
		if (bridge.pendingCount()) controller.abort();
	});
	process.once("SIGINT", () => controller.abort());
	process.once("SIGTERM", () => controller.abort());

	const log = (message) =>
		output.emit(
			message.startsWith("phase: ")
				? { type: "phase", name: message.slice("phase: ".length) }
				: { type: "log", message },
		);
	const runner = createRunner({
		pluginRoot,
		projectCwd,
		concurrency,
		timeoutMs,
		signal: controller.signal,
		log,
		invokeAgent: bridge.invoke,
	});
	await output.emit({
		type: "ready",
		protocol: PROTOCOL,
		workflow: script,
		concurrency,
		request_dir: requestDir,
	});
	try {
		const result = await runner.runFile(script, args);
		await output.emit({ type: "result", result });
	} finally {
		bridge.close();
		input.close();
		if (rawInput) process.stdin.setRawMode(false);
		await output.flush();
		await rm(requestDir, { recursive: true, force: true });
	}
}

if (
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
	main().catch(async (error) => {
		const output = createEmitter();
		await output.emit({
			type: "fatal",
			error: error.stack || error.message,
		});
		await output.flush();
		process.exitCode = 1;
	});
}
