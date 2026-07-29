#!/usr/bin/env node

import { execFile } from "node:child_process";
import { access, readFile, realpath } from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_PLUGIN_ROOT = resolve(HERE, "..");
const TOOL_MAP = new Map([
	["read", "read"],
	["write", "write"],
	["edit", "edit"],
	["bash", "bash"],
	["glob", "find"],
	["grep", "grep"],
	["ls", "ls"],
	["webfetch", "web_fetch"],
]);
const THINKING_LEVELS = new Set([
	"off",
	"minimal",
	"low",
	"medium",
	"high",
	"xhigh",
	"max",
]);

function parseFrontmatter(text, filePath) {
	const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
	if (!match) throw new Error(`invalid agent frontmatter: ${filePath}`);
	const frontmatter = {};
	for (const line of match[1].split(/\r?\n/)) {
		const field = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
		if (field) frontmatter[field[1]] = field[2].trim();
	}
	if (!frontmatter.name) throw new Error(`agent has no name: ${filePath}`);
	return { frontmatter, body: match[2].trim() };
}

function mapTools(tools = "") {
	return tools
		.split(",")
		.map((tool) => tool.trim())
		.filter(Boolean)
		.map((tool) => {
			const mapped = TOOL_MAP.get(tool.toLowerCase());
			if (!mapped) throw new Error(`unsupported Claude tool name: ${tool}`);
			return mapped;
		});
}

async function executableOnPath(name) {
	for (const dir of (process.env.PATH || "").split(":")) {
		if (!dir) continue;
		const candidate = join(dir, name);
		try {
			await access(candidate, fsConstants.X_OK);
			return candidate;
		} catch {}
	}
	return null;
}

async function findPiPackageRoot() {
	if (process.env.QUASI_PI_PACKAGE_ROOT)
		return resolve(process.env.QUASI_PI_PACKAGE_ROOT);
	try {
		const entry = createRequire(import.meta.url).resolve(
			"@earendil-works/pi-coding-agent",
		);
		let dir = dirname(entry);
		while (dirname(dir) !== dir) {
			try {
				const pkg = JSON.parse(
					await readFile(join(dir, "package.json"), "utf8"),
				);
				if (pkg.name === "@earendil-works/pi-coding-agent") return dir;
			} catch {}
			dir = dirname(dir);
		}
	} catch {}

	const command = await executableOnPath("pi");
	if (!command)
		throw new Error(
			"Pi SDK not found: install pi or set QUASI_PI_PACKAGE_ROOT",
		);
	let dir = dirname(await realpath(command));
	while (dirname(dir) !== dir) {
		try {
			const pkg = JSON.parse(await readFile(join(dir, "package.json"), "utf8"));
			if (pkg.name === "@earendil-works/pi-coding-agent") return dir;
		} catch {}
		dir = dirname(dir);
	}
	throw new Error(`Pi SDK package root not found from ${command}`);
}

function parseJson(text, source) {
	try {
		return JSON.parse(text);
	} catch (error) {
		throw new Error(`invalid JSON in ${source}: ${error.message}`);
	}
}

async function loadPiSdk() {
	const root = await findPiPackageRoot();
	const packagePath = join(root, "package.json");
	const pkg = parseJson(await readFile(packagePath, "utf8"), packagePath);
	const entry = pkg.exports?.["."]?.import || pkg.main;
	if (!entry)
		throw new Error(`Pi SDK entry missing in ${join(root, "package.json")}`);
	const sdk = await import(pathToFileURL(resolve(root, entry)).href);
	const typeboxEntry = createRequire(join(root, "package.json")).resolve(
		"typebox",
	);
	const { Type } = await import(pathToFileURL(typeboxEntry).href);
	return { sdk, Type };
}

function createSemaphore(limit) {
	let active = 0;
	const waiting = [];
	return async function withSlot(fn) {
		if (active >= limit)
			await new Promise((resolveWait) => waiting.push(resolveWait));
		active++;
		try {
			return await fn();
		} finally {
			active--;
			waiting.shift()?.();
		}
	};
}

function finalText(session) {
	const messages = session.messages || session.agent?.state?.messages || [];
	for (let i = messages.length - 1; i >= 0; i--) {
		const message = messages[i];
		if (message.role !== "assistant") continue;
		const text = (message.content || [])
			.filter((part) => part.type === "text")
			.map((part) => part.text)
			.join("\n");
		if (text) return text;
	}
	return "";
}

function modelKey(model) {
	return `${model.provider || ""}/${model.id || model.name || ""}`.toLowerCase();
}

function chooseModel(available, requested, currentProvider, currentId) {
	const currentKey =
		`${currentProvider || ""}/${currentId || ""}`.toLowerCase();
	const current =
		available.find((model) => modelKey(model) === currentKey) ||
		available.find(
			(model) =>
				(model.id || "").toLowerCase() === (currentId || "").toLowerCase(),
		);
	if (!requested) return current;
	const wanted = requested.toLowerCase();
	const exact = available.find(
		(model) =>
			modelKey(model) === wanted || (model.id || "").toLowerCase() === wanted,
	);
	if (exact) return exact;
	if (wanted === "opus" || wanted === "sonnet") {
		const alias = available.find(
			(model) =>
				modelKey(model).includes(wanted) ||
				(model.name || "").toLowerCase().includes(wanted),
		);
		if (alias) return alias;
	}
	return current;
}

function stripHtml(html) {
	return html
		.replace(/<script\b[\s\S]*?<\/script>/gi, " ")
		.replace(/<style\b[\s\S]*?<\/style>/gi, " ")
		.replace(/<[^>]+>/g, " ")
		.replace(/&nbsp;/gi, " ")
		.replace(/&amp;/gi, "&")
		.replace(/&lt;/gi, "<")
		.replace(/&gt;/gi, ">")
		.replace(/&quot;/gi, '"')
		.replace(/&#39;/gi, "'")
		.replace(/\s+/g, " ")
		.trim();
}

function readKeychainBlob() {
	return new Promise((resolve) => {
		execFile(
			"/usr/bin/security",
			["find-generic-password", "-s", "Claude Code-credentials", "-w"],
			(error, stdout) => {
				if (error) resolve(null);
				else resolve(stdout.trim() || null);
			},
		);
	});
}

export async function loadKeychainConfigs({
	readBlob = readKeychainBlob,
	log = () => {},
} = {}) {
	let blob;
	try {
		blob = await readBlob();
	} catch {
		return;
	}
	if (!blob) return;
	let data;
	try {
		data = JSON.parse(blob);
	} catch {
		return;
	}
	const secrets = data?.pluginSecrets;
	if (!secrets || typeof secrets !== "object") return;
	const pluginKey = Object.keys(secrets).find((k) => k.startsWith("quasi@"));
	if (!pluginKey) return;
	const configs = secrets[pluginKey];
	if (!configs || typeof configs !== "object") return;
	let count = 0;
	for (const [key, value] of Object.entries(configs)) {
		if (typeof value !== "string") continue;
		const envKey = `QUASI_${key.toUpperCase()}`;
		if (process.env[envKey] === undefined) {
			process.env[envKey] = value;
			count++;
		}
	}
	if (count) log(`loaded ${count} config(s) from keychain (${pluginKey})`);
}

async function createPiInvoker({ projectCwd, pluginRoot, log }) {
	await loadKeychainConfigs({ log });
	const { sdk, Type } = await loadPiSdk();
	const modelRuntime = await sdk.ModelRuntime.create();
	const availablePromise = modelRuntime.getAvailable();
	const settingsManager = sdk.SettingsManager.inMemory({
		compaction: { enabled: true },
		retry: { enabled: true, maxRetries: 2 },
	});
	const contextFiles = sdk.loadProjectContextFiles({
		cwd: projectCwd,
		agentDir: sdk.getAgentDir(),
	});

	return async ({ definition, prompt, options, signal }) => {
		const available = await availablePromise;
		const inheritedModel =
			process.env.PI_PROVIDER && process.env.PI_MODEL
				? modelRuntime.getModel(process.env.PI_PROVIDER, process.env.PI_MODEL)
				: undefined;
		const model =
			chooseModel(
				available,
				definition.model,
				process.env.PI_PROVIDER,
				process.env.PI_MODEL,
			) || inheritedModel;
		const thinkingLevel = THINKING_LEVELS.has(process.env.PI_REASONING_LEVEL)
			? process.env.PI_REASONING_LEVEL
			: undefined;
		let structuredOutput;
		const customTools = [];
		const tools = [...definition.piTools];

		if (options.schema) {
			customTools.push(
				sdk.defineTool({
					name: "structured_output",
					label: "Structured Output",
					description:
						"Return the final result matching the caller-provided JSON schema.",
					parameters: Type.Unsafe(options.schema),
					async execute(_toolCallId, params) {
						structuredOutput = params;
						return {
							content: [{ type: "text", text: "Structured result accepted." }],
							details: params,
							terminate: true,
						};
					},
				}),
			);
			tools.push("structured_output");
		}

		if (definition.piTools.includes("web_fetch")) {
			customTools.push(
				sdk.defineTool({
					name: "web_fetch",
					label: "Web Fetch",
					description:
						"Fetch one exact HTTP(S) URL and return its readable text. Only available to webcard-agent.",
					parameters: Type.Object({
						url: Type.String({
							description: "Exact URL returned by quasi-search kagi",
						}),
					}),
					async execute(_toolCallId, params, toolSignal) {
						let url;
						try {
							url = new URL(params.url);
						} catch {
							throw new Error(`invalid web_fetch URL: ${params.url}`);
						}
						if (!["http:", "https:"].includes(url.protocol))
							throw new Error("web_fetch only supports HTTP(S)");
						const fetchSignal = toolSignal
							? AbortSignal.any([toolSignal, AbortSignal.timeout(30_000)])
							: AbortSignal.timeout(30_000);
						const response = await fetch(url, { signal: fetchSignal });
						if (!response.ok)
							throw new Error(`web_fetch ${response.status}: ${url}`);
						const contentType = response.headers.get("content-type") || "";
						const body = await response.text();
						const raw = body.slice(0, 200_000);
						const text = contentType.includes("html") ? stripHtml(raw) : raw;
						return {
							content: [{ type: "text", text: text.slice(0, 80_000) }],
							details: { url: String(url) },
						};
					},
				}),
			);
		}

		const toolNote = `\nClaude tool aliases in this Pi session: Read=read, Write=write, Edit=edit, Bash=bash, Glob=find${
			definition.piTools.includes("web_fetch")
				? ", WebFetch=web_fetch. Use web_fetch only for exact URLs returned by quasi-search kagi"
				: ""
		}.`;
		const structuredNote = options.schema
			? "\nYour final action MUST be a structured_output tool call. Do not print the receipt as prose."
			: "";
		const resourceLoader = {
			getExtensions: () => ({
				extensions: [],
				errors: [],
				runtime: sdk.createExtensionRuntime(),
			}),
			getSkills: () => ({ skills: [], diagnostics: [] }),
			getPrompts: () => ({ prompts: [], diagnostics: [] }),
			getThemes: () => ({ themes: [], diagnostics: [] }),
			getAgentsFiles: () => ({ agentsFiles: contextFiles }),
			getSystemPrompt: () =>
				`${definition.body}\n\nRuntime:\n- cwd: ${projectCwd}\n- CLAUDE_PROJECT_DIR: ${projectCwd}\n- quasi plugin root: ${pluginRoot}\n- Use only the tools provided to this session.${toolNote}${structuredNote}`,
			getAppendSystemPrompt: () => [],
			extendResources: () => {},
			reload: async () => {},
		};

		const { session } = await sdk.createAgentSession({
			cwd: projectCwd,
			model,
			thinkingLevel,
			modelRuntime,
			resourceLoader,
			tools,
			customTools,
			sessionManager: sdk.SessionManager.inMemory(projectCwd),
			settingsManager,
		});

		const abort = () => session.abort().catch(() => {});
		if (signal?.aborted) abort();
		signal?.addEventListener("abort", abort, { once: true });
		try {
			await session.prompt(prompt);
			if (signal?.aborted) return null;
			return options.schema ? (structuredOutput ?? null) : finalText(session);
		} catch (error) {
			log(`agent ${options.label || definition.name} failed: ${error.message}`);
			return null;
		} finally {
			signal?.removeEventListener("abort", abort);
			session.dispose();
		}
	};
}

export function createRunner({
	pluginRoot = DEFAULT_PLUGIN_ROOT,
	projectCwd = process.env.CLAUDE_PROJECT_DIR || process.cwd(),
	concurrency = 4,
	timeoutMs = 45 * 60 * 1000,
	invokeAgent,
	signal,
	log = (message) => process.stderr.write(`[quasi-pi] ${message}\n`),
} = {}) {
	if (!Number.isInteger(concurrency) || concurrency < 1)
		throw new Error("concurrency must be a positive integer");
	if (!Number.isFinite(timeoutMs) || timeoutMs < 1)
		throw new Error("timeoutMs must be a positive number");
	const root = resolve(pluginRoot);
	const cwd = resolve(projectCwd);
	const withAgentSlot = createSemaphore(concurrency);
	const definitions = new Map();
	let realInvoker;

	process.env.CLAUDE_PROJECT_DIR = cwd;
	process.env.CLAUDE_PLUGIN_ROOT ||= root;
	process.env.PATH = `${join(root, "bin")}:${process.env.PATH || ""}`;

	async function loadDefinition(agentType) {
		if (agentType === "general-purpose")
			return {
				name: "general-purpose",
				model: null,
				body: "You are a minimal general-purpose worker. Follow the task exactly and return only the requested result.",
				piTools: ["read", "bash", "find", "grep", "ls"],
			};
		if (!agentType?.startsWith("quasi:"))
			throw new Error(`unsupported agentType: ${agentType}`);
		const name = agentType.slice("quasi:".length);
		if (!/^[a-z0-9][a-z0-9-]*$/.test(name))
			throw new Error(`invalid quasi agent name: ${name}`);
		if (definitions.has(name)) return definitions.get(name);
		const filePath = join(root, "agents", `${name}.md`);
		const parsed = parseFrontmatter(await readFile(filePath, "utf8"), filePath);
		if (parsed.frontmatter.name !== name)
			throw new Error(`agent name mismatch: ${filePath}`);
		const definition = {
			name,
			model: parsed.frontmatter.model || null,
			body: parsed.body,
			piTools: mapTools(parsed.frontmatter.tools),
			filePath,
		};
		definitions.set(name, definition);
		return definition;
	}

	async function agent(prompt, options = {}) {
		const definition = await loadDefinition(
			options.agentType || "general-purpose",
		);
		return withAgentSlot(async () => {
			const controller = new AbortController();
			const abort = () => controller.abort();
			const limit = options.timeoutMs || timeoutMs;
			const timer = setTimeout(() => {
				log(
					`agent ${options.label || definition.name} timed out after ${limit}ms`,
				);
				abort();
			}, limit);
			if (signal?.aborted) abort();
			signal?.addEventListener("abort", abort, { once: true });
			try {
				const call =
					invokeAgent ||
					(realInvoker ||= await createPiInvoker({
						projectCwd: cwd,
						pluginRoot: root,
						log,
					}));
				const work = Promise.resolve()
					.then(() =>
						call({ definition, prompt, options, signal: controller.signal }),
					)
					.catch((error) => {
						log(
							`agent ${options.label || definition.name} failed: ${error.message}`,
						);
						return null;
					});
				const aborted = controller.signal.aborted
					? Promise.resolve(null)
					: new Promise((resolveAbort) =>
							controller.signal.addEventListener(
								"abort",
								() => resolveAbort(null),
								{
									once: true,
								},
							),
						);
				return await Promise.race([work, aborted]);
			} finally {
				clearTimeout(timer);
				signal?.removeEventListener("abort", abort);
			}
		});
	}

	const parallel = (tasks) =>
		Promise.all(tasks.map((task) => Promise.resolve().then(task)));
	const phase = (name) => log(`phase: ${name}`);

	async function runSource(source, args) {
		const body = source.replace(/^export\s+const\s+meta\s*=/m, "const meta =");
		const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
		return new AsyncFunction("agent", "parallel", "phase", "log", "args", body)(
			agent,
			parallel,
			phase,
			log,
			args,
		);
	}

	return {
		agent,
		parallel,
		runSource,
		runFile: async (scriptPath, args) =>
			runSource(await readFile(resolve(scriptPath), "utf8"), args),
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
			join(pluginRoot, "skills", "process-material", "orchestrate.mjs"),
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
	const runner = createRunner({
		pluginRoot,
		projectCwd,
		concurrency: Number(cli.concurrency || 4),
		timeoutMs: Number(cli["timeout-ms"] || 45 * 60 * 1000),
		signal: controller.signal,
	});
	const result = await runner.runFile(script, args);
	process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
	main().catch((error) => {
		process.stderr.write(`[quasi-pi] ${error.stack || error.message}\n`);
		process.exitCode = 1;
	});
}
