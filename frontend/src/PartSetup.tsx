import { useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "./api";
import { MaterialButton } from "./MaterialPicker";
import { type PickTarget, PickViewer, ROLE_COLORS, type SupportMarker } from "./PickViewer";
import { type ArrowSpec, directionName } from "./sceneKit";
import type { CustomSpec, Entity, LoadSpec, Material, MeshLevel, PartInfo, Units, Vec3 } from "./types";

type Kind = "force" | "mass" | "pressure" | "moment";
type Direction = "push" | "pull" | "normal" | "-z" | "+z" | "-x" | "+x" | "-y" | "+y" | "custom";

interface Target { entity: Entity; ids: number[]; point: Vec3 | null }
interface SupportDraft extends Target { dofs: number[] }
interface LoadDraft extends Target { kind: Kind; value: number; direction: Direction; custom: Vec3 }
type Active = { type: "support" | "load"; index: number };

const G = 9.81;
const KINDS: [Kind, string, string][] = [
  ["force", "Force", "N"], ["mass", "Weight of a mass", "kg"],
  ["pressure", "Pressure", "MPa"], ["moment", "Moment (torque)", "N·m"],
];
const AXIS_ORDER: Direction[] = ["-z", "+z", "+x", "-x", "+y", "-y"];
const opposite = (d: string) => `${d[0] === "+" ? "-" : "+"}${d[1]}` as Direction;
/** Axis options, with "down"/"up" marked according to how the part sits in its file. */
const axesFor = (up: string): [Direction, string][] => [
  ...AXIS_ORDER.map((d): [Direction, string] => [d,
    `${d[0] === "-" ? "−" : "+"}${d[1].toUpperCase()}${d === up ? " (up)" : d === opposite(up) ? " (down, gravity)" : ""}`]),
  ["custom", "Custom direction…"],
];
const AXIS: Partial<Record<Direction, Vec3>> = {
  "-z": [0, 0, -1], "+z": [0, 0, 1], "-x": [-1, 0, 0], "+x": [1, 0, 0], "-y": [0, -1, 0], "+y": [0, 1, 0],
};
const ENTITY_WORD: Record<Entity, [string, string]> = {
  face: ["face", "faces"], edge: ["edge", "edges"], point: ["point", "points"],
};

const emptyTarget = (entity: Entity = "face"): Target => ({ entity, ids: [], point: null });
const newSupport = (entity: Entity = "face"): SupportDraft => ({ ...emptyTarget(entity), dofs: [1, 2, 3] });
const newLoad = (entity: Entity = "face"): LoadDraft => ({
  ...emptyTarget(entity), kind: "force", value: 50, direction: entity === "face" ? "push" : "-z", custom: [0, 0, -1],
});
const isEmpty = (t: Target) => t.ids.length === 0 && t.point === null;
const unit = (v: number[]): Vec3 => {
  const n = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
};
const neg = (v: Vec3): Vec3 => [-v[0], -v[1], -v[2]];
const fmtN = (n: number) => (Math.abs(n) >= 1000 ? `${Number((n / 1000).toPrecision(3))} kN` : `${Number(n.toPrecision(3))} N`);
const fmtP = (p: Vec3) => `(${p.map((v) => Number(v.toPrecision(4))).join(", ")})`;

function directionOf(v: number[]): { direction: Direction; custom: Vec3 } {
  const u = unit(v);
  for (const [d, a] of Object.entries(AXIS)) {
    if (a && a.every((x, i) => Math.abs(x - u[i]) < 1e-6)) return { direction: d as Direction, custom: u };
  }
  return { direction: "custom", custom: u };
}

interface Props {
  materials: Record<string, Material>;
  busy: boolean;
  aiReady: boolean;
  stage: HTMLElement | null;
  onSimulate: (spec: CustomSpec) => void;
}

/** Upload a part, pick faces, edges or points for supports and loads (or let the AI do it), simulate. */
export function PartSetup({ materials, busy, aiReady, stage, onSimulate }: Props) {
  const [part, setPart] = useState<PartInfo | null>(null);
  const [units, setUnits] = useState<Units>("mm");
  const [filter, setFilter] = useState<Entity>("face");
  const [supports, setSupports] = useState<SupportDraft[]>([newSupport()]);
  const [loads, setLoads] = useState<LoadDraft[]>([newLoad()]);
  const [active, setActive] = useState<Active>({ type: "support", index: 0 });
  const [hover, setHover] = useState<PickTarget | null>(null);
  const [material, setMaterial] = useState("pla");
  const [mesh, setMesh] = useState<MeshLevel>("medium");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [rationale, setRationale] = useState("");
  const [up, setUp] = useState("+z");

  const faceById = useMemo(() => new Map(part?.faces.map((f) => [f.id, f]) ?? []), [part]);
  const edgeById = useMemo(() => new Map(part?.edges.map((e) => [e.id, e]) ?? []), [part]);

  function reset() {
    setSupports([newSupport()]);
    setLoads([newLoad()]);
    setActive({ type: "support", index: 0 });
    setFilter("face");
    setRationale("");
  }

  async function upload(file: File) {
    if (!/\.(stl|step|stp)$/i.test(file.name)) {
      setError("Use an .stl, .step or .stp file.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      setPart(await api.uploadPart(file, units));
      reset();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function changeUnits(u: Units) {
    setUnits(u);
    if (part) setPart(await api.part(part.part_id, u));
  }

  const dropProps = {
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setDragging(true); },
    onDragLeave: () => setDragging(false),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer.files?.[0];
      if (f) upload(f);
    },
  };

  function activate(a: Active) {
    setActive(a);
    const item = a.type === "support" ? supports[a.index] : loads[a.index];
    if (item && !isEmpty(item)) setFilter(item.entity);
  }

  /** Add or remove a picked face/edge/point on the active support or load. */
  function pick(t: PickTarget) {
    setNotice("");
    const apply = <T extends Target>(item: T): T => {
      const entity = isEmpty(item) ? t.entity : item.entity;
      if (entity !== t.entity) {
        setNotice(`This ${active.type} acts on ${ENTITY_WORD[item.entity][1]}. Add a new ${active.type} for ${ENTITY_WORD[t.entity][1]}.`);
        return item;
      }
      if (t.entity === "point") return { ...item, entity, ids: [], point: t.point! };
      const ids = item.ids.includes(t.id!) ? item.ids.filter((x) => x !== t.id) : [...item.ids, t.id!];
      return { ...item, entity, ids, point: null };
    };
    const strip = <T extends Target>(item: T): T =>
      item.entity === t.entity && t.id !== undefined ? { ...item, ids: item.ids.filter((x) => x !== t.id) } : item;
    if (active.type === "support") {
      setSupports((ss) => ss.map((s, i) => (i === active.index ? apply(s) : strip(s))));
      setLoads((ls) => ls.map(strip));
    } else {
      setLoads((ls) => ls.map((l, i) => {
        if (i !== active.index) return strip(l);
        const next = apply(l);
        // sensible default directions when the entity is decided
        if (isEmpty(l) && next.entity !== "face" && (l.direction === "push" || l.direction === "pull")) {
          return { ...next, direction: "-z" };
        }
        if (isEmpty(l) && next.entity !== "face" && l.kind === "pressure") return { ...next, kind: "force" };
        return next;
      }));
      setSupports((ss) => ss.map(strip));
    }
  }

  const geometryOf = useCallback((t: Target) => {
    if (t.entity === "point" && t.point) return { at: t.point, normal: null as Vec3 | null, area: 0 };
    if (t.entity === "edge") {
      const es = t.ids.map((i) => edgeById.get(i)).filter(Boolean) as PartInfo["edges"];
      const total = es.reduce((s, e) => s + e.length_mm, 0) || 1;
      const at = [0, 1, 2].map((k) => es.reduce((s, e) => s + e.midpoint[k] * e.length_mm, 0) / total) as Vec3;
      return { at, normal: null, area: 0 };
    }
    const fs = t.ids.map((i) => faceById.get(i)).filter(Boolean) as PartInfo["faces"];
    const area = fs.reduce((s, f) => s + f.area_mm2, 0);
    const at = [0, 1, 2].map((k) => fs.reduce((s, f) => s + f.centroid[k] * f.area_mm2, 0) / (area || 1)) as Vec3;
    const n = unit([0, 1, 2].map((k) => fs.reduce((s, f) => s + f.normal[k] * f.area_mm2, 0)));
    return { at, normal: n, area };
  }, [faceById, edgeById]);

  /** Resolved load for the API, or null while incomplete. */
  const resolve = useCallback((l: LoadDraft): LoadSpec | null => {
    if (isEmpty(l) || !(l.value > 0)) return null;
    const base = { entity: l.entity, ids: l.ids, point: l.point, pressure: null, vector: null };
    const { normal } = geometryOf(l);
    if (l.kind === "pressure") return l.entity === "face" ? { ...base, kind: "pressure", pressure: l.value } : null;
    let dir: Vec3 | undefined;
    if (l.direction === "custom") dir = unit(l.custom);
    else if (l.direction === "push" || l.direction === "pull" || l.direction === "normal") {
      if (!normal) return null;
      dir = l.direction === "push" ? neg(normal) : normal;
    } else dir = AXIS[l.direction];
    if (!dir) return null;
    if (l.kind === "moment") {
      const m = l.value * 1000; // N m -> N mm
      return { ...base, kind: "moment", vector: [dir[0] * m, dir[1] * m, dir[2] * m] };
    }
    const f = l.kind === "mass" ? l.value * G : l.value;
    return { ...base, kind: "force", vector: [dir[0] * f, dir[1] * f, dir[2] * f] };
  }, [geometryOf]);

  const faceColor = useCallback((id: number) => {
    if (supports.some((s) => s.entity === "face" && s.ids.includes(id))) return ROLE_COLORS.fixed;
    const i = loads.findIndex((l) => l.entity === "face" && l.ids.includes(id));
    if (i >= 0) return active.type === "load" && i === active.index ? ROLE_COLORS.activeLoad : ROLE_COLORS.load;
    return ROLE_COLORS.none;
  }, [supports, loads, active]);

  const edgeColor = useCallback((id: number) => {
    if (supports.some((s) => s.entity === "edge" && s.ids.includes(id))) return ROLE_COLORS.fixed;
    if (loads.some((l) => l.entity === "edge" && l.ids.includes(id))) return ROLE_COLORS.activeLoad;
    return null;
  }, [supports, loads]);

  const arrows: ArrowSpec[] = useMemo(() => loads.flatMap((l) => {
    const r = resolve(l);
    if (!r) return [];
    const g = geometryOf(l);
    if (r.kind === "pressure") {
      return [{ at: g.at, normal: g.normal!, dir: neg(g.normal!), label: `${r.pressure} MPa` }];
    }
    const v = r.vector!;
    const dir = unit(v);
    const mag = Math.hypot(...v);
    return [{
      at: g.at, normal: g.normal ?? neg(dir), dir, moment: r.kind === "moment",
      label: r.kind === "moment" ? `M ${Number((mag / 1000).toPrecision(3))} N·m ${directionName(dir)}`
        : `${fmtN(mag)} ${directionName(dir)}`,
    }];
  }), [loads, resolve, geometryOf]);

  const supportMarkers: SupportMarker[] = useMemo(() => supports.flatMap((s) => {
    if (isEmpty(s)) return [];
    if (s.entity === "face") {
      return s.ids.map((id) => faceById.get(id)).filter(Boolean).map((f) => ({
        at: f!.centroid as Vec3, normal: f!.normal as Vec3, entity: "face" as Entity, dofs: s.dofs,
      }));
    }
    const g = geometryOf(s);
    return [{ at: g.at, normal: [0, 0, 1] as Vec3, entity: s.entity, dofs: s.dofs }];
  }), [supports, faceById, geometryOf]);

  const points = useMemo(() => [
    ...supports.filter((s) => s.point).map((s) => ({ at: s.point!, color: "#495057" })),
    ...loads.filter((l) => l.point).map((l) => ({ at: l.point!, color: "#e64980" })),
  ], [supports, loads]);

  const resolved = loads.map(resolve);
  const ready = part && supports.some((s) => !isEmpty(s)) && supports.every((s) => isEmpty(s) || s.dofs.length > 0)
    && resolved.every(Boolean);

  function submit() {
    if (!part || !ready) return;
    onSimulate({
      template: "custom_part", part_id: part.part_id, units, material, mesh,
      supports: supports.filter((s) => !isEmpty(s)).map((s) => ({ entity: s.entity, ids: s.ids, point: s.point, dofs: s.dofs })),
      loads: resolved as LoadSpec[],
    });
  }

  async function setupWithAI() {
    if (!part) return;
    setAiBusy(true);
    setError("");
    try {
      const gravity = opposite(up);  // down is opposite to up
      const plan = await api.planPart(aiPrompt, part.part_id, units, mesh, gravity);
      setSupports(plan.spec.supports.map((s) => ({ entity: s.entity, ids: s.ids, point: s.point, dofs: s.dofs })));
      setLoads(plan.spec.loads.map((l): LoadDraft => {
        const t = { entity: l.entity, ids: l.ids, point: l.point };
        if (l.kind === "pressure") return { ...t, kind: "pressure", value: l.pressure!, direction: "push", custom: [0, 0, -1] };
        const v = l.vector!;
        const mag = Math.hypot(...v);
        return { ...t, kind: l.kind, value: l.kind === "moment" ? mag / 1000 : mag, ...directionOf(v) };
      }));
      setMaterial(plan.spec.material);
      setRationale(plan.rationale);
      setActive({ type: "support", index: 0 });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The AI could not set up this part.");
    } finally {
      setAiBusy(false);
    }
  }

  const targetChips = (t: Target, onRemove: (id: number | null) => void) => (
    <div className="chips-row">
      {isEmpty(t) && <span className="muted">click {filter === "point" ? "a point" : `${ENTITY_WORD[filter][1]}`} on the part</span>}
      {t.point && <span className="face-chip">point {fmtP(t.point)}<button onClick={(e) => { e.stopPropagation(); onRemove(null); }}>×</button></span>}
      {t.ids.map((id) => (
        <span key={id} className="face-chip">
          {ENTITY_WORD[t.entity][0]} #{id}
          <button title="Remove" onClick={(e) => { e.stopPropagation(); onRemove(id); }}>×</button>
        </span>
      ))}
    </div>
  );
  const removeFrom = <T extends Target>(item: T, id: number | null): T =>
    id === null ? { ...item, point: null } : { ...item, ids: item.ids.filter((x) => x !== id) };

  const hoverText = (() => {
    if (!hover) return "";
    if (hover.entity === "face") {
      const f = faceById.get(hover.id!);
      if (!f) return "";
      if (f.kind === "hole" || f.kind === "cylinder") {
        return `Face #${f.id} · ${f.kind === "hole" ? "hole" : "cylinder"} Ø${Number(f.diameter_mm!.toPrecision(3))} mm · axis ${directionName(f.axis!)}`;
      }
      return `Face #${f.id} · ${f.kind === "curved" ? "curved · " : ""}${Number(f.area_mm2.toPrecision(4)).toLocaleString()} mm²${f.kind === "plane" ? ` · facing ${directionName(f.normal)}` : ""}`;
    }
    if (hover.entity === "edge") {
      const e = edgeById.get(hover.id!);
      return e ? `Edge #${e.id} · ${Number(e.length_mm.toPrecision(4))} mm · ${e.direction ? `along ${directionName(e.direction)}` : "curved"}` : "";
    }
    return `Point ${fmtP(hover.point!)} mm`;
  })();

  const activeItem = active.type === "support" ? supports[active.index] : loads[active.index];
  const activeLabel = active.type === "support" ? `support ${active.index + 1}` : `load ${active.index + 1}`;

  const stageView = part && stage && createPortal(
    <div className="pick-stage" {...dropProps}>
      <PickViewer part={part} filter={filter} faceColor={faceColor} edgeColor={edgeColor}
        onPick={pick} onHover={setHover} arrows={arrows} supports={supportMarkers} points={points} />
      <div className="pick-toolbar">
        <span>Select</span>
        {(["face", "edge", "point"] as Entity[]).map((e) => (
          <button key={e} className={filter === e ? "on" : ""} onClick={() => setFilter(e)}>
            {e === "face" ? "▢ Faces" : e === "edge" ? "╱ Edges" : "• Point"}
          </button>
        ))}
        <em>for <b>{activeLabel}</b>{activeItem && !isEmpty(activeItem) ? ` (${ENTITY_WORD[activeItem.entity][1]})` : ""}</em>
      </div>
      {notice && <div className="pick-notice">{notice}</div>}
      {hoverText && <div className="face-info">{hoverText}</div>}
      <div className="nav-help">Left-drag rotate · right-drag pan · wheel zoom · double-click focus · click the axes for views</div>
      {dragging && <div className="drop-veil">Drop to replace the part</div>}
    </div>,
    stage,
  );

  return (
    <div className="part-setup">
      <label className={`upload ${dragging ? "drag" : ""}`} {...dropProps}>
        <input type="file" accept=".stl,.step,.stp" disabled={uploading}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <b>{uploading ? "Reading the part…" : part ? "Drop or click to replace the part" : "Drop your part here"}</b>
        {!part && !uploading && <small>STL or STEP · or click to browse</small>}
      </label>
      <label className="row-inline">
        File units
        <select value={units} onChange={(e) => changeUnits(e.target.value as Units)}>
          <option value="mm">millimetres</option><option value="cm">centimetres</option>
          <option value="m">metres</option><option value="in">inches</option>
        </select>
      </label>
      {error && <p className="error">{error}</p>}

      {part && (
        <>
          <p className="hint">
            {part.bbox_mm.size.map((v) => Number(v.toPrecision(4))).join(" × ")} mm · {part.faces.length} faces ·{" "}
            {part.edges.length} edges. STL files carry no units: check the size.
          </p>

          <div className="ai-box">
            <h2>Describe how it is held and loaded</h2>
            <textarea rows={3} value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)}
              placeholder="e.g. screwed to a wall through the hole; a 5 kg box sits on the top shelf; PETG" />
            <label className="row-inline">
              In this file, “up” is
              <select value={up} onChange={(e) => {
                const next = e.target.value;
                // weights already placed follow the new "down"
                setLoads((ls) => ls.map((l) => (l.kind === "mass" && l.direction === opposite(up)
                  ? { ...l, direction: opposite(next) } : l)));
                setUp(next);
              }}>
                <option value="+z">+Z (most CAD)</option><option value="+y">+Y</option>
                <option value="-z">−Z</option><option value="-y">−Y</option>
                <option value="+x">+X</option><option value="-x">−X</option>
              </select>
            </label>
            <button className="primary" disabled={!aiPrompt.trim() || aiBusy || !aiReady}
              title={aiReady ? "" : "Set OPENAI_API_KEY or ANTHROPIC_API_KEY on the server"} onClick={setupWithAI}>
              {aiBusy ? "Reading the part…" : "✦ Set up with AI"}
            </button>
            {rationale && <p className="info">{rationale} <em>Check it on the part, and change anything below.</em></p>}
          </div>

          <h2>Supports</h2>
          <div className="roles">
            {supports.map((s, i) => (
              <div key={i} className={`role-card fixed ${active.type === "support" && active.index === i ? "on" : ""}`}
                onClick={() => activate({ type: "support", index: i })}>
                <div className="role-title">
                  <span className="dot fixed" /> Support {i + 1}
                  <span className="dofs">
                    {[1, 2, 3].map((d) => (
                      <button key={d} className={s.dofs.includes(d) ? "on" : ""} title={`Hold ${"XYZ"[d - 1]}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSupports((ss) => ss.map((x, j) => j !== i ? x
                            : { ...x, dofs: x.dofs.includes(d) ? x.dofs.filter((y) => y !== d) : [...x.dofs, d].sort() }));
                        }}>{"XYZ"[d - 1]}</button>
                    ))}
                  </span>
                  {supports.length > 1 && <button className="x" onClick={(e) => {
                    e.stopPropagation(); setSupports((ss) => ss.filter((_, j) => j !== i)); setActive({ type: "support", index: 0 });
                  }}>×</button>}
                </div>
                <p className="muted">{s.dofs.length === 3 ? "Fixed: cannot move in any direction"
                  : s.dofs.length === 0 ? "Pick at least one direction to hold"
                  : `Holds ${s.dofs.map((d) => "XYZ"[d - 1]).join(" and ")} only; slides freely otherwise`}</p>
                {targetChips(s, (id) => setSupports((ss) => ss.map((x, j) => (j === i ? removeFrom(x, id) : x))))}
              </div>
            ))}
            <button className="add" onClick={() => { setSupports((ss) => [...ss, newSupport(filter)]); setActive({ type: "support", index: supports.length }); }}>
              + Add a support
            </button>
          </div>

          <h2>Loads</h2>
          <div className="roles">
            {loads.map((l, i) => {
              const r = resolved[i];
              const unitLabel = KINDS.find((k) => k[0] === l.kind)![2];
              const kinds = KINDS.filter(([k]) => (k === "pressure" ? l.entity === "face" || isEmpty(l)
                : k === "moment" ? l.entity !== "point" : true));
              const dirs: [Direction, string][] = l.kind === "moment"
                ? [...(l.entity === "face" ? [["normal", "About the face normal (twist)"] as [Direction, string]] : []), ...axesFor(up)]
                : [...(l.entity === "face" ? [["push", "Push into the face"], ["pull", "Pull out of the face"]] as [Direction, string][] : []), ...axesFor(up)];
              return (
                <div key={i} className={`role-card load ${active.type === "load" && active.index === i ? "on" : ""}`}
                  onClick={() => activate({ type: "load", index: i })}>
                  <div className="role-title">
                    <span className="dot load" /> Load {i + 1}
                    {loads.length > 1 && <button className="x" onClick={(e) => {
                      e.stopPropagation(); setLoads((ls) => ls.filter((_, j) => j !== i)); setActive({ type: "support", index: 0 });
                    }}>×</button>}
                  </div>
                  {targetChips(l, (id) => setLoads((ls) => ls.map((x, j) => (j === i ? removeFrom(x, id) : x))))}
                  <div className="load-grid">
                    <select value={l.kind} onChange={(e) => {
                      const kind = e.target.value as Kind;
                      const direction: Direction = kind === "moment" ? (l.entity === "face" ? "normal" : "+z")
                        : kind === "mass" ? opposite(up) : l.entity === "face" ? "push" : "-z";
                      setLoads((ls) => ls.map((x, j) => (j === i ? { ...x, kind, direction } : x)));
                    }}>
                      {kinds.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                    <div className="with-unit">
                      <input type="number" min={0} step="any" value={l.value}
                        onChange={(e) => setLoads((ls) => ls.map((x, j) => (j === i ? { ...x, value: Number(e.target.value) } : x)))} />
                      <em>{unitLabel}</em>
                    </div>
                    {l.kind !== "pressure" ? (
                      <select className="span2" value={l.direction}
                        onChange={(e) => setLoads((ls) => ls.map((x, j) => (j === i ? { ...x, direction: e.target.value as Direction } : x)))}>
                        {dirs.map(([k, label]) => <option key={k} value={k}>{l.kind === "moment" && k !== "normal" && k !== "custom" ? `About ${label}` : label}</option>)}
                      </select>
                    ) : <p className="span2 muted">Perpendicular to the surface everywhere, pressing into it.</p>}
                    {l.kind !== "pressure" && l.direction === "custom" && (
                      <div className="span2 vec">
                        {(["X", "Y", "Z"] as const).map((ax, k) => (
                          <label key={ax}>{ax}
                            <input type="number" step="any" value={l.custom[k]} onChange={(e) => {
                              const c = [...l.custom] as Vec3;
                              c[k] = Number(e.target.value);
                              setLoads((ls) => ls.map((x, j) => (j === i ? { ...x, custom: c } : x)));
                            }} />
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="resolved">
                    {!r ? "Pick where it acts and give a value above zero."
                      : r.kind === "pressure" ? <>= <b>{r.pressure} MPa</b> over {r.ids.length} face{r.ids.length > 1 ? "s" : ""}</>
                      : r.kind === "moment" ? <>= <b>{Number((Math.hypot(...r.vector!) / 1000).toPrecision(3))} N·m</b> about <b>{directionName(unit(r.vector!))}</b> (right-hand rule)</>
                      : <>= <b>{fmtN(Math.hypot(...r.vector!))}</b> along <b>{directionName(unit(r.vector!))}</b>
                        {r.entity !== "point" && <> spread over {r.ids.length} {ENTITY_WORD[r.entity][r.ids.length > 1 ? 1 : 0]}</>}</>}
                  </div>
                </div>
              );
            })}
            <button className="add" onClick={() => { setLoads((ls) => [...ls, newLoad(filter)]); setActive({ type: "load", index: loads.length }); }}>
              + Add a load
            </button>
          </div>

          <MaterialButton materials={materials} value={material} onChange={setMaterial} />
          <div className="form">
            <label className="row"><span>Mesh</span>
              <select value={mesh} onChange={(e) => setMesh(e.target.value as MeshLevel)}>
                <option value="coarse">Coarse (fastest)</option>
                <option value="medium">Medium</option>
                <option value="fine">Fine (most accurate)</option>
              </select>
            </label>
          </div>
          <button className="primary" disabled={!ready || busy} onClick={submit}>
            {busy ? "Simulating…" : ready ? "Simulate my part" : "Add a support and a complete load"}
          </button>
        </>
      )}
      {stageView}
      {!part && stage && createPortal(
        <div className={`drop-stage ${dragging ? "drag" : ""}`} {...dropProps}>
          <div>
            <b>Drop an STL or STEP file anywhere here</b>
            <p>Then pick faces, edges or points for supports and loads, or describe them and let the AI set it up.</p>
          </div>
        </div>,
        stage,
      )}
    </div>
  );
}
