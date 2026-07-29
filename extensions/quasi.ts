import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "..");

export default function (pi: ExtensionAPI) {
	pi.on("resources_discover", async () => ({
		skillPaths: [join(PLUGIN_ROOT, "skills")],
	}));
}
