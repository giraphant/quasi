#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { build } from "esbuild";

const ROOT = resolve(import.meta.dirname, "..");
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const source = resolve(ROOT, request.source);

const runtime = () => {
  const outputs = [...(request.outputs || [])];
  let agentCalls = 0;
  let pipelineCalls = 0;
  return {
    host: {
      agent: async () => {
        agentCalls += 1;
        return outputs.shift() ?? null;
      },
      pipeline: async (items, worker) => {
        pipelineCalls += 1;
        return Promise.all(items.map(worker));
      },
    },
    report: (value) => ({ value, agentCalls, pipelineCalls }),
  };
};

if (request.action === "run-generated") {
  const generated = await readFile(source, "utf8");
  const body = generated.replace(/^export const meta =/m, "const meta =");
  // The real Workflow sandbox provides core ECMAScript plus the host's own
  // helpers only. A bare vm context is the closest available stand-in: nothing
  // web-platform (URL, fetch, TextEncoder) may be injected here, or a generated
  // entry that depends on one passes in test and fails in the sandbox.
  const execute = runInNewContext(
    `(async (agent, pipeline, args) => {\n${body}\n})`,
    {
      // Host replay forbids reading wall-clock time; explicit date validation is OK.
      Date: class WorkflowDate extends Date {
        constructor(...args) {
          if (!args.length) throw new Error("new Date() is unavailable in workflow scripts");
          super(...args);
        }
        static now() { throw new Error("Date.now() is unavailable in workflow scripts"); }
      },
    },
  );
  const { host, report } = runtime();
  const agentRequests = [];
  const observedAgent = async (prompt, options) => {
    agentRequests.push({ prompt, options });
    return host.agent(prompt, options);
  };
  const value = await execute(observedAgent, host.pipeline, request.input);
  process.stdout.write(JSON.stringify({ ...report(value), ...(request.captureAgentRequests ? { agentRequests } : {}) }));
  process.exit(0);
}

const result = await build({
  absWorkingDir: ROOT,
  bundle: true,
  charset: "utf8",
  entryPoints: [source],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  metafile: request.action === "inputs",
  platform: "node",
  sourcemap: false,
  target: ["es2022"],
  treeShaking: true,
  write: false,
});

if (request.action === "inputs") {
  process.stdout.write(JSON.stringify(Object.keys(result.metafile.inputs)));
  process.exit(0);
}

if (result.outputFiles.length !== 1)
  throw new Error(`expected one bundled test module, got ${result.outputFiles.length}`);

const bundled = result.outputFiles[0].text;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(bundled).toString("base64")}`;
const loaded = await import(moduleUrl);
if (request.action === "read") {
  process.stdout.write(JSON.stringify(loaded[request.export]));
  process.exit(0);
}

const target = loaded[request.export];
if (typeof target !== "function")
  throw new Error(`named export is not callable: ${request.export}`);

if (request.action === "run") {
  const { host, report } = runtime();
  const value = await target(host, request.input);
  process.stdout.write(JSON.stringify(report(value)));
  process.exit(0);
}

const value = await target(...(request.args || []));
process.stdout.write(
  JSON.stringify(value, (_key, item) =>
    item instanceof Map ? { __map_entries__: [...item.entries()] } : item,
  ),
);
