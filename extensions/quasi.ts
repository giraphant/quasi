import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

export default function (pi: ExtensionAPI) {
  pi.on("resources_discover", async () => ({
    skillPaths: [join(PLUGIN_ROOT, "skills")],
  }));
}
