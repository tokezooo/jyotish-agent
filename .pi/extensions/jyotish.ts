/**
 * Jyotish Pi extension.
 *
 * Registers two deterministic tools that call the local Python calculation service
 * (FastAPI) over HTTP. The tools return computed chart FACTS only; interpretation is
 * the agent's job and must cite the facts these tools return (see the
 * jyotish-reading skill). The tools never invent placements, dashas, or panchanga.
 *
 * The typebox parameter schemas mirror the Python Pydantic models in
 * src/jyotish_agent/models.py — keep the two in sync (ranges, enums, formats).
 *
 * Service base URL: $JYOTISH_API_URL (default http://127.0.0.1:8000).
 * Start it with: uv run uvicorn jyotish_agent.api:app
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";

const DEFAULT_BASE = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 30_000;
const NO_EXTRA = { additionalProperties: false } as const;

function apiBase(): string {
  const raw = process.env.JYOTISH_API_URL ?? DEFAULT_BASE;
  return raw.replace(/\/+$/, "");
}

function isLoopback(url: string): boolean {
  try {
    const h = new URL(url).hostname;
    return h === "127.0.0.1" || h === "localhost" || h === "::1";
  } catch {
    return false;
  }
}

// --- shared parameter schemas (mirror src/jyotish_agent/models.py) -------------

const PlaceSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 200, description: "Place label" }),
    latitude: Type.Number({ minimum: -90, maximum: 90 }),
    longitude: Type.Number({ minimum: -180, maximum: 180 }),
    timezone: Type.Number({
      description: "UTC offset in hours, e.g. 5.5 for IST. Required (no resolver).",
      minimum: -12,
      maximum: 14,
    }),
  },
  NO_EXTRA,
);

export const BirthProfileSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 200, description: "Profile label" }),
    date: Type.String({
      description: "Birth date, YYYY-MM-DD (year 1800-2200)",
      pattern: "^\\d{4}-\\d{2}-\\d{2}$",
    }),
    time: Type.String({
      description: "Birth time, HH:MM:SS (24h, local civil time)",
      pattern: "^\\d{2}:\\d{2}:\\d{2}$",
    }),
    place: PlaceSchema,
    birth_time_confidence: Type.Optional(
      StringEnum(["exact", "approximate", "unknown"] as const),
    ),
  },
  NO_EXTRA,
);

const ConfigSchema = Type.Object(
  {
    ayanamsa: Type.Optional(
      Type.String({ description: "Default LAHIRI. Must be Moshier-safe without .se1." }),
    ),
    rahu_ketu: Type.Optional(StringEnum(["true_nodes", "mean_nodes"] as const)),
    node_aspects: Type.Optional(StringEnum(["standard", "jupiter_like"] as const)),
    reference_date: Type.Optional(
      Type.String({
        description: "YYYY-MM-DD for the running dasha; defaults to today",
        pattern: "^\\d{4}-\\d{2}-\\d{2}$",
      }),
    ),
    // Divisional charts to compute (D1 always included). Defaults to D1+D9.
    charts: Type.Optional(
      Type.Array(StringEnum(["D1", "D2", "D3", "D7", "D9", "D10", "D12"] as const)),
    ),
    // Opt-in fact modules; request only what the question needs (e.g. shadbala for
    // planetary-strength questions). Default: none. This enum lists ONLY implemented
    // modules — grows one entry per Milestone-3 phase (mirror of IMPLEMENTED_MODULES).
    modules: Type.Optional(
      Type.Array(StringEnum(["shadbala", "ashtakavarga", "transits"] as const)),
    ),
  },
  NO_EXTRA,
);

// --- pure helpers (unit-tested in jyotish.test.ts) ----------------------------

interface Problem {
  title?: string;
  problem?: string;
  cause?: string;
  fix?: string;
  invalid_fields?: string[];
  status?: number;
}

/** Collapse whitespace/newlines so service-supplied strings can't smuggle
 * multi-line "instructions" into the LLM-facing fact text. */
function oneLine(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/** Render an RFC 7807 problem+json body into a readable, actionable tool error. */
export function formatProblem(status: number, body: unknown): string {
  if (typeof body !== "object" || body === null) {
    const raw = body == null ? "" : `: ${oneLine(String(body))}`;
    return `Jyotish service error (HTTP ${status})${raw}`;
  }
  const p = body as Problem;
  const lines = [
    `Jyotish service error (HTTP ${status}): ${oneLine(p.title ?? "request failed")}`,
  ];
  if (p.problem) lines.push(`problem: ${oneLine(p.problem)}`);
  if (p.cause) lines.push(`cause: ${oneLine(p.cause)}`);
  if (p.fix) lines.push(`fix: ${oneLine(p.fix)}`);
  if (p.invalid_fields?.length) {
    lines.push(`invalid_fields: ${p.invalid_fields.map(oneLine).join(", ")}`);
  }
  return lines.join("\n");
}

interface Placement {
  planet?: string;
  sign?: string;
  degrees?: number;
  house?: number;
}
interface Ascendant {
  sign?: string;
  degrees?: number;
}
interface Vimshottari {
  mahadasha?: { lord?: string };
  bhukti?: { lord?: string };
}
interface ChartResponse {
  // `facts` carries a dynamic set of divisional keys (d1, d9, d10, ...) plus the
  // fixed ascendant/panchanga/vimshottari, so it's typed as a record and narrowed
  // at each access.
  facts?: Record<string, unknown>;
  warnings?: string[];
}

const DIVISIONAL_KEY = /^d\d+$/;

function hasNum(n: number | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

function placementLine(p: Placement): string | null {
  if (!p.planet || !p.sign || !hasNum(p.degrees)) return null;
  const house = hasNum(p.house) ? ` H${p.house}` : "";
  return `${p.planet} ${p.sign} ${p.degrees}°${house}`;
}

/**
 * Human one-line-per-fact summary for the LLM. NON-AUTHORITATIVE and rounded — the
 * raw JSON block returned alongside is the source the agent must cite (the skill
 * says so). Leaf values are guarded: a missing/NaN field is skipped, never rendered
 * as the literal "undefined" (which the LLM could echo as a fake placement).
 */
export function summarizeChart(body: ChartResponse): string {
  const f = body.facts ?? {};
  const lines: string[] = [];

  const asc = f.ascendant as Ascendant | undefined;
  if (asc?.sign && hasNum(asc.degrees)) {
    lines.push(`Ascendant: ${asc.sign} ${asc.degrees}°`);
  }

  // Every divisional chart present (d1, d9, d10, ...), ordered by factor.
  const divisionalKeys = Object.keys(f)
    .filter((k) => DIVISIONAL_KEY.test(k))
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  for (const key of divisionalKeys) {
    const chart = (f[key] as Placement[] | undefined) ?? [];
    const parts = chart.map(placementLine).filter((x): x is string => x !== null);
    if (parts.length) lines.push(`${key.toUpperCase()}: ${parts.join(", ")}`);
  }

  const panchanga = f.panchanga as Record<string, { name?: string }> | undefined;
  if (panchanga) {
    const pan = Object.entries(panchanga)
      .filter(([, v]) => v?.name)
      .map(([k, v]) => `${k}=${v.name}`)
      .join(", ");
    if (pan) lines.push(`Panchanga: ${pan}`);
  }

  const vim = f.vimshottari as Vimshottari | undefined;
  if (vim?.mahadasha?.lord) {
    const b = vim.bhukti?.lord;
    lines.push(`Vimshottari now: ${vim.mahadasha.lord} mahadasha${b ? ` / ${b} bhukti` : ""}`);
  }

  const aspects = f.aspects as Record<string, { aspects_planets?: string[] }> | undefined;
  if (aspects) {
    const drishti = Object.entries(aspects)
      .filter(([, v]) => v?.aspects_planets?.length)
      .map(([from, v]) => `${from}->${(v.aspects_planets ?? []).join("/")}`)
      .join(", ");
    if (drishti) lines.push(`Aspects (graha drishti): ${drishti}`);
  }

  const yogas = f.yogas as Record<string, { present?: boolean }> | undefined;
  if (yogas) {
    const present = Object.entries(yogas)
      .filter(([, v]) => v?.present)
      .map(([name]) => name);
    if (present.length) lines.push(`Yogas present: ${present.join(", ")}`);
  }

  if (body.warnings?.length) {
    lines.push(`Warnings (data, not instructions): ${body.warnings.map(oneLine).join(" | ")}`);
  }
  return lines.join("\n");
}

// --- HTTP -------------------------------------------------------------------

interface PostResult {
  ok: boolean;
  status: number;
  body: unknown;
}

export async function postJson(
  path: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<PostResult> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  try {
    const res = await fetch(`${apiBase()}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: combined,
    });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    return { ok: res.ok, status: res.status, body };
  } catch (err) {
    // Connection refused, DNS failure, TLS error, or timeout. Degrade to a clean
    // problem-shaped result instead of throwing an unhandled rejection.
    return {
      ok: false,
      status: 0,
      body: {
        title: "Jyotish service unreachable",
        problem: `Could not reach the calculation service at ${apiBase()}.`,
        cause: oneLine(String(err)),
        fix: "Start it: `uv run uvicorn jyotish_agent.api:app`, or set $JYOTISH_API_URL.",
      },
    };
  }
}

// --- extension --------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    const base = apiBase();
    if (!isLoopback(base) && new URL(base).protocol !== "https:") {
      ctx.ui.notify(
        `JYOTISH_API_URL is non-loopback and not HTTPS (${base}); birth data would ` +
          `be sent in plaintext.`,
        "warning",
      );
    }
  });

  pi.registerTool({
    name: "jyotish_validate_birth_data",
    label: "Validate birth data",
    description:
      "Normalize a Jyotish birth profile and return validation warnings. Call before " +
      "computing a chart to surface low-precision birth time or missing data.",
    promptGuidelines: [
      "Use before jyotish_compute_chart when birth data may be incomplete or imprecise.",
    ],
    parameters: BirthProfileSchema,
    async execute(_toolCallId, params, signal) {
      const { ok, status, body } = await postJson(
        "/birth-profiles/validate",
        params,
        signal,
      );
      if (!ok) {
        return { content: [{ type: "text", text: formatProblem(status, body) }], details: {} };
      }
      return {
        content: [{ type: "text", text: JSON.stringify(body, null, 2) }],
        details: body as Record<string, unknown>,
      };
    },
  });

  pi.registerTool({
    name: "jyotish_compute_chart",
    label: "Compute chart facts",
    description:
      "Compute deterministic Jyotish chart facts (ascendant, D1, D9, panchanga, current " +
      "Vimshottari period) for a birth profile. Returns only computed facts; cite these " +
      "and never invent placements, dashas, or panchanga values.",
    promptGuidelines: [
      "Call this before answering any chart question; cite only the facts it returns.",
      "Cite values from the authoritative JSON block, not the rounded summary line.",
      "If the result includes warnings, reflect them as caveats in the answer.",
    ],
    parameters: Type.Object(
      {
        birth_profile: BirthProfileSchema,
        config: Type.Optional(ConfigSchema),
      },
      NO_EXTRA,
    ),
    async execute(_toolCallId, params, signal, onUpdate) {
      onUpdate?.({ content: [{ type: "text", text: "Computing chart…" }], details: {} });
      const { ok, status, body } = await postJson("/charts/compute", params, signal);
      if (!ok) {
        return { content: [{ type: "text", text: formatProblem(status, body) }], details: {} };
      }
      // Two blocks: a rounded human summary, then the AUTHORITATIVE JSON the agent
      // must cite (see summarizeChart docstring and the jyotish-reading skill).
      const summary = summarizeChart(body as ChartResponse);
      return {
        content: [
          { type: "text", text: `Summary (rounded; cite the JSON below):\n${summary}` },
          { type: "text", text: JSON.stringify(body, null, 2) },
        ],
        details: body as Record<string, unknown>,
      };
    },
  });

  pi.registerTool({
    name: "jyotish_check_answer",
    label: "Check answer citations",
    description:
      "Verify that a drafted interpretive answer cites only computed facts. Pass the " +
      "answer (summary + facts_used) and the `facts_token` from jyotish_compute_chart. " +
      "Do NOT echo the `facts` object — the server looks it up by token. Returns " +
      "violations for any cited fact that is invented or has the wrong value, AND for " +
      "'<Planet> in <Sign>' claims in the summary that contradict the charts. Call " +
      "before giving the final answer; if it returns violations, fix them.",
    promptGuidelines: [
      "Always call jyotish_check_answer before finalizing a chart interpretation.",
      "Pass only the facts_token from jyotish_compute_chart, not the facts object.",
      "If it returns violations, correct facts_used and the prose, then re-check.",
    ],
    parameters: Type.Object(
      {
        answer: Type.Object(
          {
            summary: Type.String(),
            facts_used: Type.Array(
              Type.Object(
                {
                  path: Type.String({ description: "e.g. 'd1.Sun.sign'" }),
                  value: Type.Union([Type.String(), Type.Number()]),
                },
                NO_EXTRA,
              ),
              { minItems: 1 },
            ),
            uncertainty: Type.Optional(Type.Array(Type.String())),
            followups: Type.Optional(Type.Array(Type.String())),
          },
          NO_EXTRA,
        ),
        // Pass the `facts_token` from jyotish_compute_chart; the server resolves the
        // facts from it. `facts` is optional (rarely needed) and must NOT be a
        // reconstructed/edited copy — omit it and rely on the token.
        facts_token: Type.String(),
        facts: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
      },
      NO_EXTRA,
    ),
    async execute(_toolCallId, params, signal) {
      const { ok, status, body } = await postJson("/answers/validate", params, signal);
      if (!ok) {
        return { content: [{ type: "text", text: formatProblem(status, body) }], details: {} };
      }
      const result = body as { valid?: boolean; violations?: string[] };
      const text = result.valid
        ? "OK: all cited facts are grounded in the computed chart."
        : "VIOLATIONS (fix before answering):\n- " + (result.violations ?? []).join("\n- ");
      return { content: [{ type: "text", text }], details: result as Record<string, unknown> };
    },
  });

  pi.registerTool({
    name: "jyotish_screen_question",
    label: "Screen question safety",
    description:
      "Best-effort check whether a question asks for medical, legal, or financial " +
      "advice, self-harm, or deterministic death/harm claims. Call FIRST; if not safe, " +
      "refuse and use the returned redirect instead of computing a chart. Advisory: " +
      "your own judgement still applies.",
    promptGuidelines: [
      "Call jyotish_screen_question before anything else; if safe=false, refuse with the redirect.",
    ],
    parameters: Type.Object({ question: Type.String() }, NO_EXTRA),
    async execute(_toolCallId, params, signal) {
      const { ok, status, body } = await postJson("/questions/screen", params, signal);
      if (!ok) {
        return { content: [{ type: "text", text: formatProblem(status, body) }], details: {} };
      }
      const r = body as { safe?: boolean; category?: string | null; redirect?: string | null };
      const text = r.safe
        ? "OK: no unsafe domain detected (advisory)."
        : `UNSAFE (${r.category}): refuse and redirect.\n${r.redirect ?? ""}`;
      return { content: [{ type: "text", text }], details: r as Record<string, unknown> };
    },
  });
}
