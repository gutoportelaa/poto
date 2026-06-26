// Rebuilda dist/ quando src/, styles ou HTML mudam (dev).
import { watch } from "node:fs";
import { join } from "node:path";

const ROOT = import.meta.dir;
let timer: ReturnType<typeof setTimeout> | null = null;

function rebuild() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    console.log("[watch] rebuild…");
    const proc = Bun.spawnSync(["bun", "run", "build.ts"], {
      cwd: ROOT,
      stdout: "inherit",
      stderr: "inherit",
    });
    if (proc.exitCode !== 0) console.error("[watch] build falhou");
  }, 120);
}

watch(join(ROOT, "src"), { recursive: true }, (_, f) => {
  if (f?.endsWith(".ts") || f?.endsWith(".css")) rebuild();
});
for (const f of ["index.html", "painel.html"]) {
  watch(join(ROOT, f), rebuild);
}

console.log("[watch] observando src/ e HTML…");
