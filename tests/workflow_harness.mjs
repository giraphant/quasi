#!/usr/bin/env node

import { resolve } from "node:path";

import { build } from "esbuild";

const ROOT = resolve(import.meta.dirname, "..");
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const source = resolve(ROOT, request.source);

const result = await build({
  absWorkingDir: ROOT,
  bundle: true,
  charset: "utf8",
  entryPoints: [source],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  platform: "node",
  sourcemap: false,
  target: ["es2022"],
  treeShaking: true,
  write: false,
});

if (result.outputFiles.length !== 1)
  throw new Error(`expected one bundled test module, got ${result.outputFiles.length}`);

const bundled = result.outputFiles[0].text;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(bundled).toString("base64")}`;
const loaded = await import(moduleUrl);
const target = loaded[request.export];
if (typeof target !== "function")
  throw new Error(`named export is not callable: ${request.export}`);

const value = await target(...(request.args || []));
process.stdout.write(
  JSON.stringify(value, (_key, item) =>
    item instanceof Map ? { __map_entries__: [...item.entries()] } : item,
  ),
);
