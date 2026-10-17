import strings from "./en-ste.json";

type Tree = { [k: string]: string | Tree };
const root = strings as Tree;
const missing = new Set<string>();

/** Return the UI string for a key. Replace each {name} with the value from params. */
export function t(key: string, params?: Record<string, string | number>): string {
  let node: string | Tree | undefined = root;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string") {
      node = undefined;
      break;
    }
    node = node[part];
  }
  if (typeof node !== "string") {
    if (!missing.has(key)) {
      missing.add(key);
      console.warn(`i18n: missing key ${key}`);
    }
    return key;
  }
  if (!params) return node;
  return node.replace(/\{(\w+)\}/g, (_m, name: string) =>
    params[name] === undefined ? `{${name}}` : String(params[name]),
  );
}

/** Return true if the key has a UI string. */
export function hasKey(key: string): boolean {
  let node: string | Tree | undefined = root;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string") return false;
    node = node[part];
  }
  return typeof node === "string";
}
