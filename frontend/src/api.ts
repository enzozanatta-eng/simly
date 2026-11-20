import type { CustomSpec, Health, Material, PartInfo, Spec, StudyResult, Units } from "./types";

export class ApiError extends Error {}

/** Turn a FastAPI error body into one readable sentence. */
function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (d.declined) {
      return `This can't be simulated yet: ${d.declined}` +
        (d.closest ? ` (closest: ${d.closest})` : "");
    }
    if (Array.isArray(d.errors)) {
      return d.errors.map((e: { field: string; message: string }) =>
        `${e.field}: ${e.message.replace(/^Value error, /, "")}`).join("; ");
    }
    if (d.error) return String(d.error);
  }
  return "Something went wrong.";
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(describe((data as { detail?: unknown }).detail));
  return data as T;
}

export const api = {
  health: () => call<Health>("/api/health"),
  materials: () => call<Record<string, Material>>("/api/materials"),
  plan: (prompt: string) =>
    call<{ spec: Spec; attempts: { error: string | null }[] }>("/api/plan", { prompt }),
  uploadPart: async (file: File, units: Units): Promise<PartInfo> => {
    const form = new FormData();
    form.append("file", file);
    form.append("units", units);
    const res = await fetch("/api/parts", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(describe((data as { detail?: unknown }).detail));
    return data as PartInfo;
  },
  part: (id: string, units: Units) => call<PartInfo>(`/api/parts/${id}?units=${units}`),
  planPart: (prompt: string, partId: string, units: Units, mesh: string) =>
    call<{ spec: CustomSpec; rationale: string }>("/api/plan_part", { prompt, part_id: partId, units, mesh }),
  simulate: (spec: Spec | CustomSpec, convergence: boolean) =>
    call<StudyResult>("/api/simulate", { spec, convergence }),
  explain: (prompt: string, result: StudyResult) =>
    call<{ explanation: string }>("/api/explain", { prompt, result }),
};
