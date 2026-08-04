from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "workflow_harness.mjs"


def run_workflow_export(
    source: str,
    export_name: str,
    *args: Any,
) -> Any:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    request = {
        "source": source,
        "export": export_name,
        "args": args,
    }
    proc = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def inspect_typescript_contract(source: str) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = r"""
import { readFileSync } from "node:fs";
import ts from "typescript";

const path = process.argv[1];
const text = readFileSync(path, "utf8");
const source = ts.createSourceFile(path, text, ts.ScriptTarget.ES2022, true);
const localTypes = [];
const imports = {};
const interfaces = {};
const functions = {};

for (const statement of source.statements) {
  if (ts.isImportDeclaration(statement) && statement.importClause) {
    const moduleName = statement.moduleSpecifier.text;
    const names = [];
    const bindings = statement.importClause.namedBindings;
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements) names.push(element.name.text);
    }
    imports[moduleName] = names;
  }
  if (ts.isInterfaceDeclaration(statement)) {
    localTypes.push(statement.name.text);
    interfaces[statement.name.text] = {
      extends: (statement.heritageClauses || []).flatMap((clause) =>
        clause.types.map((item) => item.expression.getText(source)),
      ),
    };
  }
  if (ts.isTypeAliasDeclaration(statement)) localTypes.push(statement.name.text);
  if (ts.isVariableStatement(statement)) {
    for (const declaration of statement.declarationList.declarations) {
      if (
        ts.isIdentifier(declaration.name) &&
        declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        functions[declaration.name.text] = declaration.initializer.parameters.map(
          (parameter) => parameter.type?.getText(source) || null,
        );
      }
    }
  }
}

process.stdout.write(JSON.stringify({ localTypes, imports, interfaces, functions }));
"""
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, str(ROOT / source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)
