// Bundla os clientes (totem + painel) para ./dist com o bundler do Bun.
export {};

const out = await Bun.build({
  entrypoints: ["./src/totem.ts", "./src/painel.ts"],
  outdir: "./dist",
  target: "browser",
  minify: true,
  sourcemap: "none",
});

if (!out.success) {
  console.error("Falha no build:");
  for (const log of out.logs) console.error(log);
  process.exit(1);
}
await Bun.write("./dist/build-id.txt", new Date().toISOString());
console.log(`Build OK — ${out.outputs.length} artefatos em ./dist`);
