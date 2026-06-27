/** Material Symbols Rounded (FILL 0) — ver DESIGN.md §6 */
export const SYM = {
  saude: "stethoscope",
  seguranca: "shield",
  mulher: "female",
  outros: "info",
  mic: "mic",
  panic: "emergency",
  back: "arrow_back",
  send: "send",
  video: "videocam",
  check: "check",
  close: "close",
} as const;

export function sym(name: string, size = "lg"): string {
  return `<span class="sym sym-${size}" aria-hidden="true">${name}</span>`;
}
