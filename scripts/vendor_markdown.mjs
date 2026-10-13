/* Reproduce the bundled parser from the exact package-lock.json dependency. */
import {readFile, writeFile, mkdir} from "node:fs/promises";
const source = new URL("../node_modules/marked/", import.meta.url);
const target = new URL("../custom_components/chatgpt_assist/frontend/vendor/", import.meta.url);
await mkdir(target, {recursive: true});
const script = (await readFile(new URL("lib/marked.esm.js", source), "utf8")).replace(/^\/\/# sourceMappingURL=.*\n?/gm, "");
await writeFile(new URL("marked.js", target), script);
await writeFile(new URL("marked.LICENSE", target), await readFile(new URL("LICENSE", source)));
