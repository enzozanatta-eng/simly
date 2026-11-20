import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { Legend, Results } from "./Results";
import { StudyForm, TEMPLATES } from "./StudyForm";
import { Logo } from "./Logo";
import { PartSetup } from "./PartSetup";
import type { CustomSpec, Health, Material, Spec, StudyResult } from "./types";
import { Viewer } from "./Viewer";

const EXAMPLES = [
  "A 3D-printed PETG shelf bracket, 120 mm long, 20 x 15 mm section, holding 3 kg at the end",
  "Steel diving board, 2 m long, 50 cm wide, 4 cm thick, with a 90 kg person at the tip",
  "Aluminium plate 300 x 100 x 6 mm with a 25 mm hole, pulled with 20 kN",
  "Viga de aço engastada de 1 m, seção 50 x 80 mm, com 1 kN na ponta",
];

type Busy = null | "plan" | "simulate" | "explain";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [materials, setMaterials] = useState<Record<string, Material>>({});
  const [prompt, setPrompt] = useState("");
  const [spec, setSpec] = useState<Spec>(TEMPLATES.cantilever_beam.example);
  const [result, setResult] = useState<StudyResult | null>(null);
  const [explanation, setExplanation] = useState("");
  const [convergence, setConvergence] = useState(false);
  const [exaggeration, setExaggeration] = useState(0.08);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [mode, setMode] = useState<"part" | "examples">("part");
  // in "Your part" mode the stage shows either the face-picking view or the results
  const [partView, setPartView] = useState<"setup" | "results">("setup");
  const [resultMode, setResultMode] = useState<"part" | "examples">("part");
  const [stageEl, setStageEl] = useState<HTMLElement | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.materials().then(setMaterials).catch(() => setMaterials({}));
  }, []);

  async function run<T>(kind: Busy, job: () => Promise<T>): Promise<T | undefined> {
    setBusy(kind);
    setError("");
    try {
      return await job();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Cannot reach the Simly server.");
    } finally {
      setBusy(null);
    }
  }

  async function simulate(s: Spec | CustomSpec) {
    setExplanation("");
    const r = await run("simulate", () => api.simulate(s, convergence));
    if (r) {
      setResult(r);
      setResultMode(s.template === "custom_part" ? "part" : "examples");
      if (s.template === "custom_part") setPartView("results");
    }
  }

  async function planAndSimulate() {
    setInfo("");
    const plan = await run("plan", () => api.plan(prompt));
    if (!plan) return;
    const retries = plan.attempts.filter((a) => a.error).length;
    setInfo(retries
      ? `The AI's first proposal broke a physics rule and was corrected (${retries}x).`
      : "The AI set up the study below. You can adjust any value.");
    setSpec(plan.spec);
    await simulate(plan.spec);
  }

  async function explain() {
    if (!result) return;
    const r = await run("explain", () => api.explain(prompt, result));
    if (r) setExplanation(r.explanation);
  }

  const aiReady = Boolean(health?.ai_provider);
  const showSetupStage = mode === "part" && (partView === "setup" || resultMode !== "part" || !result);
  const showResult = result && !showSetupStage && (mode === resultMode);

  return (
    <div className="app">
      <header>
        <h1><Logo /> Simly</h1>
        <p>Describe a part. Get a verified simulation, explained like in class.</p>
        {health && (
          <ul className="status">
            <li className={health.solver ? "ok" : "off"}>CalculiX</li>
            <li className={health.mesher ? "ok" : "off"}>Gmsh</li>
            <li className={aiReady ? "ok" : "off"}>AI {health.ai_provider ?? "off"}</li>
          </ul>
        )}
      </header>

      <main>
        <aside>
          <div className="tabs">
            <button className={mode === "part" ? "on" : ""} onClick={() => setMode("part")}>Your part</button>
            <button className={mode === "examples" ? "on" : ""} onClick={() => setMode("examples")}>Textbook examples</button>
          </div>

          <label className="check">
            <input type="checkbox" checked={convergence}
              onChange={(e) => setConvergence(e.target.checked)} />
            Verify accuracy with a mesh convergence study (3 meshes, GCI)
          </label>

          {mode === "part" ? (
            <section>
              <PartSetup materials={materials} busy={busy !== null} onSimulate={simulate} aiReady={aiReady}
                stage={showSetupStage ? stageEl : null} />
            </section>
          ) : (
            <>
              <section>
                <h2>1. Describe it</h2>
                <textarea
                  rows={3}
                  placeholder="e.g. a steel shelf bracket 300 mm long holding 20 kg at the end"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
                <div className="chips">
                  {EXAMPLES.map((ex) => (
                    <button key={ex} className="chip" onClick={() => setPrompt(ex)}>{ex}</button>
                  ))}
                </div>
                <button
                  className="primary"
                  disabled={!prompt.trim() || busy !== null || !aiReady}
                  title={aiReady ? "" : "Set OPENAI_API_KEY or ANTHROPIC_API_KEY on the server"}
                  onClick={planAndSimulate}
                >
                  {busy === "plan" ? "Setting up…" : "Set up and simulate"}
                </button>
                {info && <p className="info">{info}</p>}
              </section>

              <section>
                <h2>2. Check the setup</h2>
                <StudyForm spec={spec} materials={materials} onChange={setSpec} />
                <button className="primary" disabled={busy !== null} onClick={() => simulate(spec)}>
                  {busy === "simulate" ? "Simulating…" : "Simulate"}
                </button>
              </section>
            </>
          )}
          {error && <p className="error">{error}</p>}
        </aside>

        <section className="stage">
          {showSetupStage ? (
            <div className="stage-slot" ref={setStageEl}>
              {busy === "simulate" && <div className="busy-veil">Meshing and solving…</div>}
            </div>
          ) : showResult && result ? (
            <>
              {resultMode === "part" && (
                <button className="back" onClick={() => setPartView("setup")}>← Back to supports and loads</button>
              )}
              <div className="viewer-wrap">
                <Viewer display={result.display} exaggeration={exaggeration} />
                <div className="overlay">
                  <Legend range={result.display.range} />
                  <label>
                    Deformation ×
                    <input type="range" min={0} max={0.25} step={0.01} value={exaggeration}
                      onChange={(e) => setExaggeration(Number(e.target.value))} />
                  </label>
                </div>
              </div>
              <Results result={result} />
              <div className="explain">
                <button disabled={busy !== null || !aiReady} onClick={explain}>
                  {busy === "explain" ? "Writing…" : "Explain it like in class"}
                </button>
                {explanation && <div className="explanation">{explanation}</div>}
              </div>
            </>
          ) : (
            <div className="empty">
              {busy === "simulate" || busy === "plan"
                ? "Meshing and solving…"
                : mode === "part"
                  ? "Upload an STL or STEP file on the left, click the faces that are fixed and loaded, then simulate."
                  : "Describe a part on the left, or press Simulate to run the example."}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
