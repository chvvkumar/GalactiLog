export type MetricType = "gauge" | "counter" | "histogram" | "summary" | "untyped";

export interface Sample {
  labels: Record<string, string>;
  value: number;
}

export interface MetricFamily {
  name: string;
  type: MetricType;
  help: string;
  samples: Sample[];
}

function parseValue(raw: string): number {
  const s = raw.trim();
  if (s === "NaN") return NaN;
  if (s === "+Inf" || s === "Inf") return Infinity;
  if (s === "-Inf") return -Infinity;
  const n = Number(s);
  return n;
}

function parseLabels(inner: string): Record<string, string> {
  const labels: Record<string, string> = {};
  let i = 0;
  const n = inner.length;
  while (i < n) {
    while (i < n && (inner[i] === " " || inner[i] === "," || inner[i] === "\t")) i++;
    if (i >= n) break;
    let keyStart = i;
    while (i < n && inner[i] !== "=") i++;
    if (i >= n) break;
    const key = inner.slice(keyStart, i).trim();
    i++;
    while (i < n && inner[i] === " ") i++;
    if (i >= n || inner[i] !== '"') break;
    i++;
    let val = "";
    while (i < n) {
      const c = inner[i];
      if (c === "\\") {
        const nx = inner[i + 1];
        if (nx === "\\") { val += "\\"; i += 2; continue; }
        if (nx === '"') { val += '"'; i += 2; continue; }
        if (nx === "n") { val += "\n"; i += 2; continue; }
        val += nx ?? "";
        i += 2;
        continue;
      }
      if (c === '"') { i++; break; }
      val += c;
      i++;
    }
    labels[key] = val;
  }
  return labels;
}

function parseSampleLine(line: string): { name: string; sample: Sample } | null {
  let i = 0;
  const n = line.length;
  while (i < n && line[i] !== "{" && line[i] !== " " && line[i] !== "\t") i++;
  const name = line.slice(0, i);
  if (!name) return null;
  let labels: Record<string, string> = {};
  if (i < n && line[i] === "{") {
    i++;
    // find matching close, respecting quoted strings
    let depth = 1;
    let start = i;
    while (i < n && depth > 0) {
      const c = line[i];
      if (c === '"') {
        i++;
        while (i < n) {
          if (line[i] === "\\") { i += 2; continue; }
          if (line[i] === '"') { i++; break; }
          i++;
        }
        continue;
      }
      if (c === "}") { depth--; if (depth === 0) break; }
      i++;
    }
    labels = parseLabels(line.slice(start, i));
    if (i < n && line[i] === "}") i++;
  }
  while (i < n && (line[i] === " " || line[i] === "\t")) i++;
  if (i >= n) return null;
  // value until next whitespace (timestamp ignored)
  let vStart = i;
  while (i < n && line[i] !== " " && line[i] !== "\t") i++;
  const valStr = line.slice(vStart, i);
  const value = parseValue(valStr);
  if (valStr.length === 0) return null;
  return { name, sample: { labels, value } };
}

function baseNameFor(sampleName: string, familyName: string, type: MetricType): string {
  if (type === "histogram") {
    if (sampleName === familyName + "_bucket") return familyName;
    if (sampleName === familyName + "_sum") return familyName;
    if (sampleName === familyName + "_count") return familyName;
  }
  if (type === "summary") {
    if (sampleName === familyName + "_sum") return familyName;
    if (sampleName === familyName + "_count") return familyName;
  }
  return sampleName;
}

export function parsePrometheusText(text: string): MetricFamily[] {
  const lines = text.split(/\r?\n/);
  const families = new Map<string, MetricFamily>();
  const helpByName = new Map<string, string>();
  const typeByName = new Map<string, MetricType>();

  for (const rawLine of lines) {
    const line = rawLine;
    if (!line) continue;
    if (line.startsWith("#")) {
      const rest = line.slice(1).trimStart();
      if (rest.startsWith("HELP ")) {
        const after = rest.slice(5);
        const sp = after.indexOf(" ");
        if (sp > 0) {
          const mname = after.slice(0, sp);
          const help = after.slice(sp + 1);
          helpByName.set(mname, help);
          const fam = families.get(mname);
          if (fam) fam.help = help;
        }
        continue;
      }
      if (rest.startsWith("TYPE ")) {
        const after = rest.slice(5);
        const sp = after.indexOf(" ");
        if (sp > 0) {
          const mname = after.slice(0, sp);
          const tword = after.slice(sp + 1).trim() as MetricType;
          const t: MetricType = (["gauge", "counter", "histogram", "summary", "untyped"] as MetricType[])
            .includes(tword) ? tword : "untyped";
          typeByName.set(mname, t);
          if (!families.has(mname)) {
            families.set(mname, {
              name: mname,
              type: t,
              help: helpByName.get(mname) ?? "",
              samples: [],
            });
          } else {
            const fam = families.get(mname)!;
            fam.type = t;
          }
        }
        continue;
      }
      continue;
    }
    const parsed = parseSampleLine(line);
    if (!parsed) continue;
    const { name: sampleName, sample } = parsed;

    // Determine owning family: try each known family whose base matches
    let owner: MetricFamily | null = null;
    for (const [fname, fam] of families) {
      if (baseNameFor(sampleName, fname, fam.type) === fname) {
        owner = fam;
        break;
      }
    }
    if (!owner) {
      for (const suffix of ["_bucket", "_sum", "_count"]) {
        if (sampleName.endsWith(suffix)) {
          const base = sampleName.slice(0, -suffix.length);
          const fam = families.get(base);
          if (fam) { owner = fam; break; }
        }
      }
    }
    if (!owner) {
      const t = typeByName.get(sampleName) ?? "untyped";
      owner = {
        name: sampleName,
        type: t,
        help: helpByName.get(sampleName) ?? "",
        samples: [],
      };
      families.set(sampleName, owner);
    }
    // For histogram _bucket samples, retain the `le` label verbatim and include original sample name context via labels
    const labels = sample.labels;
    if (owner.type === "histogram" || owner.type === "summary") {
      const suffix = sampleName === owner.name
        ? ""
        : sampleName.slice(owner.name.length);
      if (suffix) labels["__suffix__"] = suffix;
    }
    owner.samples.push({ labels, value: sample.value });
  }

  return Array.from(families.values());
}
