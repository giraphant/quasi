interface ImportMeta {
  readonly url: string;
}

declare const process: {
  readonly argv: string[];
  readonly env: Record<string, string | undefined>;
  readonly stdout: { write(value: string): void };
};

declare const Buffer: {
  byteLength(value: string, encoding?: string): number;
};

declare module "node:fs/promises" {
  export const readFile: any;
  export const writeFile: any;
}

declare module "node:child_process" {
  export const execFile: any;
}

declare module "node:path" {
  export const dirname: any;
  export const join: any;
  export const resolve: any;
}

declare module "node:url" {
  export const fileURLToPath: any;
  export const pathToFileURL: any;
}

declare module "node:util" {
  export const promisify: any;
}
