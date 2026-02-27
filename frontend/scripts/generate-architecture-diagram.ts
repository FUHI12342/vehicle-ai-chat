#!/usr/bin/env node
/**
 * Architecture diagram generator
 *
 * Scans frontend & backend source files and outputs a Mermaid diagram
 * definition to src/lib/architecture-diagram.ts.
 *
 * Usage: npx tsx scripts/generate-architecture-diagram.ts
 */

import {
  readFileSync,
  readdirSync,
  writeFileSync,
  existsSync,
  mkdirSync,
} from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

// ─── Paths ───────────────────────────────────────────────

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FRONTEND = resolve(__dirname, "..");
const ROOT = resolve(FRONTEND, "..");
const BACKEND = join(ROOT, "backend");
const OUT = join(FRONTEND, "src", "lib", "architecture-diagram.ts");

// ─── Helpers ─────────────────────────────────────────────

function readDir(dir: string, filter: (f: string) => boolean): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter(filter).sort();
}

function readFile(filePath: string): string {
  return readFileSync(filePath, "utf-8");
}

function toPascalCase(s: string): string {
  return s.replace(/(^|_)(\w)/g, (_, __, c: string) => c.toUpperCase());
}

function chunkArray<T>(arr: T[], size: number): T[][] {
  const result: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
}

// ─── Scanners ────────────────────────────────────────────

/** Frontend chat components → file names without extension */
function scanComponents(): string[] {
  const dir = join(FRONTEND, "src", "components", "chat");
  return readDir(dir, (f) => f.endsWith(".tsx")).map((f) =>
    f.replace(/\.tsx$/, ""),
  );
}

/** Frontend hooks → file names without extension */
function scanHooks(): string[] {
  const dir = join(FRONTEND, "src", "hooks");
  return readDir(dir, (f) => f.endsWith(".ts") && !f.startsWith("_")).map(
    (f) => f.replace(/\.ts$/, ""),
  );
}

/** Backend API routers → node ID + first decorated path */
function scanAPIRouters(): { id: string; path: string }[] {
  const dir = join(BACKEND, "app", "api");
  const skip = new Set(["__init__.py", "router.py"]);
  const files = readDir(dir, (f) => f.endsWith(".py") && !skip.has(f));

  return files.map((file) => {
    const content = readFile(join(dir, file));
    const match = content.match(
      /@router\.(get|post|put|delete|patch)\(["']([^"']+)["']/,
    );
    const base = file.replace(/\.py$/, "");
    const id = toPascalCase(base) + "Router";
    return { id, path: match?.[2] ?? `/${base}` };
  });
}

/** Backend service classes */
function scanServices(): string[] {
  const dir = join(BACKEND, "app", "services");
  const files = readDir(
    dir,
    (f) => f.endsWith(".py") && !f.startsWith("_"),
  );
  const classes: string[] = [];
  for (const file of files) {
    const content = readFile(join(dir, file));
    for (const m of content.matchAll(/^class\s+(\w+)/gm)) {
      classes.push(m[1]);
    }
  }
  return classes;
}

/** ChatStep enum member values from session.py */
function scanChatSteps(): string[] {
  const file = join(BACKEND, "app", "models", "session.py");
  if (!existsSync(file)) return [];

  const content = readFile(file);
  const enumBlock = content.match(/class ChatStep[\s\S]*?(?=\nclass |\n$)/);
  if (!enumBlock) return [];

  const steps: string[] = [];
  for (const m of enumBlock[0].matchAll(/^\s+\w+\s*=\s*"([^"]+)"/gm)) {
    steps.push(m[1]);
  }
  return steps;
}

/** LLM providers → node ID + display_name */
const PROVIDER_ID_MAP: Record<string, string> = {
  openai: "OpenAI",
};

function scanProviders(): { id: string; displayName: string }[] {
  const dir = join(BACKEND, "app", "llm");
  const files = readDir(dir, (f) => f.endsWith("_provider.py"));

  return files.map((file) => {
    const content = readFile(join(dir, file));
    const displayMatch = content.match(/display_name\s*=\s*"([^"]+)"/);
    const nameMatch = content.match(/^\s+name\s*=\s*"([^"]+)"/m);
    const name = nameMatch?.[1] ?? file.replace(/_provider\.py$/, "");
    const id = PROVIDER_ID_MAP[name] ?? name[0].toUpperCase() + name.slice(1);
    return { id, displayName: displayMatch?.[1] ?? id };
  });
}

/** RAG pipeline: stable node ID + scanned main class + annotation */
const RAG_NODE_CONFIG: Record<string, { id: string; annotation: string }> = {
  "pdf_loader.py": { id: "PDFLoader", annotation: "PyPDF2" },
  "chunker.py": { id: "Chunker", annotation: "content-type 分類" },
  "embedder.py": { id: "Embedder", annotation: "OpenAI / local" },
  "vector_store.py": { id: "ChromaDB", annotation: "vehicle_manuals" },
};

const RAG_PIPELINE_ORDER = [
  "pdf_loader.py",
  "chunker.py",
  "embedder.py",
  "vector_store.py",
];

function scanRAG(): {
  id: string;
  className: string;
  annotation?: string;
}[] {
  const dir = join(BACKEND, "app", "rag");
  const nodes: { id: string; className: string; annotation?: string }[] = [];

  for (const file of RAG_PIPELINE_ORDER) {
    const filePath = join(dir, file);
    if (!existsSync(filePath)) continue;
    const content = readFile(filePath);
    // Use the last class in file — in Python, the main class typically comes
    // after helper dataclasses / base classes.
    const allClasses = [...content.matchAll(/^class\s+(\w+)/gm)];
    const className =
      (allClasses.length > 0 ? allClasses[allClasses.length - 1][1] : null) ??
      toPascalCase(file.replace(/\.py$/, ""));
    const config = RAG_NODE_CONFIG[file];
    if (config) {
      nodes.push({ id: config.id, className, annotation: config.annotation });
    }
  }
  return nodes;
}

/** Data files (non-.py) → node ID + filename as label */
const DATA_NODE_MAP: Record<string, string> = {
  "vehicles.json": "VehiclesJSON",
};

function scanDataFiles(): { id: string; label: string }[] {
  const dir = join(BACKEND, "app", "data");
  const files = readDir(
    dir,
    (f) => !f.endsWith(".py") && !f.startsWith("_") && !f.startsWith("."),
  );
  return files.map((f) => ({
    id: DATA_NODE_MAP[f] ?? toPascalCase(f.replace(/\.\w+$/, "")),
    label: f,
  }));
}

// ─── Template Constants ──────────────────────────────────

const SERVICE_ANNOTATIONS: Record<string, string> = {
  SessionStore: "（in-memory + TTL）",
  UrgencyAssessor: "keyword + LLM 二段階",
};

const FIXED_DATA_NODES = [
  { id: "PDFs", label: "PDF マニュアル" },
  { id: "ChromaData", label: "chroma_data/" },
];

const CHAT_FLOW_EDGES = [
  "S1 --> S2",
  "S2 --> S3",
  "S3 --> S4",
  "S3 --> S5",
  "S4 --> S5",
  "S5 --> S6",
  "S5 --> S7",
  "S6 --> S7",
  "S7 --> S8",
  "S8 --> S9",
  "S9 --> S10",
  "S3 -.->|CRITICAL| S7",
  "S5 -.->|resolved| S10",
];

const RAG_PIPELINE_EDGES = ["PDFLoader --> Chunker --> Embedder --> ChromaDB"];

// Inter-layer edges grouped by position in diagram
const EDGES_AFTER_SERVICES = [
  "ChatRouter --> ChatService",
  "ChatService --> SessionStore",
  "VehiclesRouter --> VehicleService",
  "ChatService --> RAGService",
  "ChatService --> UrgencyAssessor",
];

const EDGES_AFTER_CHAT_FLOW = ["ChatService --> ChatFlow"];

const EDGES_AFTER_LLM = [
  "ChatFlow --> Registry",
  "UrgencyAssessor --> Registry",
  "ProvidersRouter --> Registry",
];

const EDGES_AFTER_RAG = [
  "RAGService --> ChromaDB",
  "AdminRouter --> PDFLoader",
];

const EDGES_AFTER_DATA = [
  "VehicleService --> VehiclesJSON",
  "PDFLoader --> PDFs",
  "ChromaDB --> ChromaData",
];

const STYLES = [
  "",
  "  %% ─── Styles ───",
  "  classDef frontend fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f",
  "  classDef proxy fill:#e0e7ff,stroke:#6366f1,color:#312e81",
  "  classDef api fill:#fef3c7,stroke:#f59e0b,color:#78350f",
  "  classDef service fill:#d1fae5,stroke:#10b981,color:#064e3b",
  "  classDef flow fill:#fce7f3,stroke:#ec4899,color:#831843",
  "  classDef llm fill:#ede9fe,stroke:#8b5cf6,color:#4c1d95",
  "  classDef rag fill:#ffedd5,stroke:#f97316,color:#7c2d12",
  "  classDef data fill:#f1f5f9,stroke:#64748b,color:#1e293b",
  "",
  "  class Frontend frontend",
  "  class Proxy proxy",
  "  class BackendAPI api",
  "  class Services service",
  "  class ChatFlow flow",
  "  class LLM llm",
  "  class RAG rag",
  "  class Data data",
].join("\n");

// ─── Generator ───────────────────────────────────────────

function generate(): string {
  const components = scanComponents();
  const hooks = scanHooks();
  const routers = scanAPIRouters();
  const services = scanServices();
  const steps = scanChatSteps();
  const providers = scanProviders();
  const ragNodes = scanRAG();
  const dataFiles = scanDataFiles();

  const I1 = "  ";
  const I2 = "    ";

  const componentLines = chunkArray(components, 4).map((g) => g.join(" / "));
  const componentLabel = ["UI Components", ...componentLines].join("<br/>");
  const hookLabel = ["Hooks", hooks.join(" / ")].join("<br/>");

  const lines: string[] = [];

  // ── Frontend Layer
  lines.push("graph TB");
  lines.push(`${I1}%% ─── Frontend Layer ───`);
  lines.push(
    `${I1}subgraph Frontend["Frontend （Next.js 15 / React 19）"]`,
  );
  lines.push(`${I2}UI["${componentLabel}"]`);
  lines.push(`${I2}Hooks["${hookLabel}"]`);
  lines.push(`${I2}APIClient["API Client<br/>lib/api.ts"]`);
  lines.push(`${I2}UI --> Hooks --> APIClient`);
  lines.push(`${I1}end`);
  lines.push("");

  // ── Next.js Proxy
  lines.push(`${I1}%% ─── Next.js Proxy ───`);
  lines.push(`${I1}subgraph Proxy["Next.js API Proxy"]`);
  lines.push(`${I2}ProxyRoute["/api/* → FastAPI"]`);
  lines.push(`${I1}end`);
  lines.push("");
  lines.push(`${I1}APIClient --> ProxyRoute`);
  lines.push("");

  // ── Backend API Layer
  lines.push(`${I1}%% ─── Backend API Layer ───`);
  lines.push(`${I1}subgraph BackendAPI["Backend API （FastAPI）"]`);
  for (const r of routers) {
    lines.push(`${I2}${r.id}["${r.path}"]`);
  }
  lines.push(`${I1}end`);
  lines.push("");
  lines.push(`${I1}ProxyRoute --> BackendAPI`);
  lines.push("");

  // ── Service Layer
  lines.push(`${I1}%% ─── Service Layer ───`);
  lines.push(`${I1}subgraph Services["Services"]`);
  for (const svc of services) {
    const ann = SERVICE_ANNOTATIONS[svc];
    const label = ann ? `${svc}<br/>${ann}` : svc;
    lines.push(`${I2}${svc}["${label}"]`);
  }
  lines.push(`${I1}end`);
  lines.push("");
  for (const e of EDGES_AFTER_SERVICES) lines.push(`${I1}${e}`);
  lines.push("");

  // ── Chat Flow State Machine
  lines.push(`${I1}%% ─── Chat Flow State Machine ───`);
  lines.push(`${I1}subgraph ChatFlow["Chat Flow State Machine"]`);
  lines.push(`${I2}direction LR`);
  for (let i = 0; i < steps.length; i++) {
    lines.push(`${I2}S${i + 1}["${steps[i]}"]`);
  }
  for (const e of CHAT_FLOW_EDGES) lines.push(`${I2}${e}`);
  lines.push(`${I1}end`);
  lines.push("");
  for (const e of EDGES_AFTER_CHAT_FLOW) lines.push(`${I1}${e}`);
  lines.push("");

  // ── LLM Layer
  lines.push(`${I1}%% ─── LLM Layer ───`);
  lines.push(`${I1}subgraph LLM["LLM Layer"]`);
  lines.push(`${I2}Registry["ProviderRegistry"]`);
  for (const p of providers) {
    lines.push(`${I2}${p.id}["${p.displayName}"]`);
  }
  for (const p of providers) {
    lines.push(`${I2}Registry --> ${p.id}`);
  }
  lines.push(`${I1}end`);
  lines.push("");
  for (const e of EDGES_AFTER_LLM) lines.push(`${I1}${e}`);
  lines.push("");

  // ── RAG Pipeline
  lines.push(`${I1}%% ─── RAG Pipeline ───`);
  lines.push(`${I1}subgraph RAG["RAG Pipeline"]`);
  for (const n of ragNodes) {
    const label = n.annotation
      ? `${n.className}<br/>${n.annotation}`
      : n.className;
    lines.push(`${I2}${n.id}["${label}"]`);
  }
  for (const e of RAG_PIPELINE_EDGES) lines.push(`${I2}${e}`);
  lines.push(`${I1}end`);
  lines.push("");
  for (const e of EDGES_AFTER_RAG) lines.push(`${I1}${e}`);
  lines.push("");

  // ── Data Layer
  lines.push(`${I1}%% ─── Data Layer ───`);
  lines.push(`${I1}subgraph Data["Data Layer"]`);
  for (const d of dataFiles) {
    lines.push(`${I2}${d.id}["${d.label}"]`);
  }
  for (const d of FIXED_DATA_NODES) {
    lines.push(`${I2}${d.id}["${d.label}"]`);
  }
  lines.push(`${I1}end`);
  lines.push("");
  for (const e of EDGES_AFTER_DATA) lines.push(`${I1}${e}`);

  // ── Styles
  lines.push(STYLES);

  return lines.join("\n");
}

// ─── Main ────────────────────────────────────────────────

const mermaid = generate();

const output = `// AUTO-GENERATED — do not edit manually
// Run: npm run generate:architecture

export const architectureDiagram = \`
${mermaid}
\`;
`;

const outDir = dirname(OUT);
if (!existsSync(outDir)) {
  mkdirSync(outDir, { recursive: true });
}

writeFileSync(OUT, output, "utf-8");
console.log(`✓ Generated ${OUT}`);
