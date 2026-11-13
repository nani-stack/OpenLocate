// The one Node API the contract test uses. Declared here instead of adding @types/node, so the
// browser code cannot accidentally type-check against Node globals.
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}
