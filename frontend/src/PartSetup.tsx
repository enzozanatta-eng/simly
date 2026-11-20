import { useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "./api";
import { PickViewer, ROLE_COLORS } from "./PickViewer";
import { type ArrowSpec, directionName } from "./sceneKit";
import { MaterialButton } from "./MaterialPicker";
import type { CustomSpec, Material, MeshLevel, PartFace, PartInfo, Units } from "./types";

type Vec3 = [number, number, number];
type Kind = "force" | "mass" | "pressure";
type Direction = "push" | "pull" | "-z" | "+z" | "-x" | "+x" | "-y" | "+y" | "custom";

interface LoadDraft {
  faces: number[];
  kind: Kind;
  value: number;
  direction: Direction;
  custom: Vec3;
}

const G = 9.81;
const KINDS: [Kind, string, string][] = [
  ["force", "Force", "N"],
  ["mass", "Weight of a mass", "kg"],
  ["pressure", "Pressure", "MPa"],
];
const DIRECTIONS: [Direction, string][] = [
  ["push", "Push into the face"], ["pull", "Pull out of the face"],
  ["-z", "−Z (down)"], ["+z", "+Z (up)"], ["+x", "+X"], ["-x", "−X"], ["+y", "+Y"], ["-y", "−Y"],
  ["custom", "Custom direction…"],
];
const AXIS: Partial<Record<Direction, Vec3>> = {
  "-z": [0, 0, -1], "+z": [0, 0, 1], "-x": [-1, 0, 0], "+x": [1, 0, 0], "-y": [0, -1, 0], "+y": [0, 1, 0],
};

const newLoad = (): LoadDraft => ({ faces: [], kind: "force", value: 50, direction: "-z", custom: [0, 0, -1] });
const unit = (v: number[]): Vec3 => {
  const n = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / n, v[1] / n, v[2] / n];
};
const fmtN = (n: number) => (Math.abs(n) >= 1000 ? `${Number((n / 1000).toPrecision(3))} kN` : `${Number(n.toPrecision(3))} N`);

/** Area-weighted centroid, outward normal and area of a set of faces. */
function faceSet(faces: PartFace[]) {
  const area = faces.reduce((s, f) => s + f.area_mm2, 0);
  const c = [0, 0, 0], n = [0, 0, 0];
  for (const f of faces) {
    for (let i = 0; i < 3; i++) {
      c[i] += (f.centroid[i] * f.area_mm2) / (area || 1);
      n[i] += f.normal[i] * f.area_mm2;
    }
  }
  return { at: c as Vec3, normal: unit(n), area };
}

const axisWord = (n: number[]) => {
  const d = directionName(n);
  return d.startsWith("(") ? "an angle" : d;
};

interface Props {
  materials: Record<string, Material>;
  busy: boolean;
  /** where the large 3D picking view is drawn (the main stage), when visible */
  stage: HTMLElement | null;
  onSimulate: (spec: CustomSpec) => void;
}

/** Upload a part, click its faces to fix and load it, then simulate. */
export function PartSetup({ materials, busy, stage, onSimulate }: Props) {
  const [part, setPart] = useState<PartInfo | null>(null);
  const [units, setUnits] = useState<Units>("mm");
  const [fixed, setFixed] = useState<number[]>([]);
  const [loads, setLoads] = useState<LoadDraft[]>([newLoad()]);
  const [active, setActive] = useState<"fixed" | number>("fixed");
  const [hover, setHover] = useState<number | null>(null);
  const [material, setMaterial] = useState("pla");
  const [mesh, setMesh] = useState<MeshLevel>("medium");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);

  const faceById = useMemo(() => new Map(part?.faces.map((f) => [f.id, f]) ?? []), [part]);

  async function upload(file: File) {
    if (!/\.(stl|step|stp)$/i.test(file.name)) {
      setError("Use an .stl, .step or .stp file.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      setPart(await api.uploadPart(file, units));
      setFixed([]);
      setLoads([newLoad()]);
      setActive("fixed");
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

  const toggle = (list: number[], f: number) => (list.includes(f) ? list.filter((x) => x !== f) : [...list, f]);

  function pick(face: number) {
    if (active === "fixed") {
      setFixed((fs) => toggle(fs, face));
      setLoads((ls) => ls.map((l) => ({ ...l, faces: l.faces.filter((x) => x !== face) })));
    } else {
      setLoads((ls) => ls.map((l, i) => (i === active ? { ...l, faces: toggle(l.faces, face) } : l)));
      setFixed((fs) => fs.filter((x) => x !== face));
    }
  }

  const update = (i: number, patch: Partial<LoadDraft>) =>
    setLoads((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  /** Force vector in N for a load, or null while it is incomplete. */
  const forceOf = useCallback((l: LoadDraft): Vec3 | null => {
    const faces = l.faces.map((f) => faceById.get(f)).filter(Boolean) as PartFace[];
    if (!faces.length || !(l.value > 0)) return null;
    const { normal, area } = faceSet(faces);
    if (l.kind === "pressure") {
      const total = l.value * area; // MPa x mm2 = N, pressing into the face
      return [-normal[0] * total, -normal[1] * total, -normal[2] * total];
    }
    const magnitude = l.kind === "mass" ? l.value * G : l.value;
    const dir = l.direction === "push" ? normal.map((v) => -v)
      : l.direction === "pull" ? normal
      : l.direction === "custom" ? unit(l.custom)
      : AXIS[l.direction]!;
    return [dir[0] * magnitude, dir[1] * magnitude, dir[2] * magnitude];
  }, [faceById]);

  const colorOf = useCallback((face: number) => {
    if (fixed.includes(face)) return ROLE_COLORS.fixed;
    const i = loads.findIndex((l) => l.faces.includes(face));
    if (i >= 0) return i === active ? ROLE_COLORS.activeLoad : ROLE_COLORS.load;
    return ROLE_COLORS.none;
  }, [fixed, loads, active]);

  const arrows: ArrowSpec[] = useMemo(() => loads.flatMap((l) => {
    const f = forceOf(l);
    if (!f) return [];
    const { at, normal } = faceSet(l.faces.map((x) => faceById.get(x)!).filter(Boolean));
    const dir = unit(f);
    return [{ at, normal, dir, label: `${fmtN(Math.hypot(...f))} ${directionName(dir)}` }];
  }), [loads, forceOf, faceById]);

  const supports = useMemo(() => {
    const faces = fixed.map((x) => faceById.get(x)).filter(Boolean) as PartFace[];
    return faces.map((f) => ({ at: f.centroid as Vec3, normal: f.normal as Vec3 }));
  }, [fixed, faceById]);

  const ready = part && fixed.length > 0 && loads.every((l) => forceOf(l) !== null);
  const hovered = hover !== null ? faceById.get(hover) : undefined;

  function submit() {
    if (!part || !ready) return;
    onSimulate({
      template: "custom_part", part_id: part.part_id, units, fixed_faces: fixed,
      loads: loads.map((l) => ({ faces: l.faces, force: forceOf(l)! })), material, mesh,
    });
  }

  const chips = (faces: number[], remove: (f: number) => void) => (
    <div className="chips-row">
      {faces.length === 0 && <span className="muted">no faces yet: click them on the part</span>}
      {faces.map((f) => (
        <span key={f} className="face-chip">
          #{f}
          <button title="Remove" onClick={(e) => { e.stopPropagation(); remove(f); }}>×</button>
        </span>
      ))}
    </div>
  );

  const stageView = part && stage && createPortal(
    <div className="pick-stage" {...dropProps}>
      <PickViewer part={part} colorOf={colorOf} onPick={pick} onHover={setHover}
        arrows={arrows} supports={supports} />
      <div className="pick-hint">
        {active === "fixed"
          ? <><span className="dot fixed" /> Click the faces that are <b>held fixed</b></>
          : <><span className="dot load" /> Click the faces where <b>load {active + 1}</b> acts</>}
      </div>
      {hovered && (
        <div className="face-info">
          Face #{hovered.id} · {Number(hovered.area_mm2.toPrecision(4)).toLocaleString()} mm² · facing {axisWord(hovered.normal)}
        </div>
      )}
      <div className="legend-roles">
        <span><i style={{ background: ROLE_COLORS.fixed.getStyle() }} />Fixed</span>
        <span><i style={{ background: ROLE_COLORS.activeLoad.getStyle() }} />Load</span>
        <span><i style={{ background: ROLE_COLORS.hover.getStyle() }} />Under cursor</span>
      </div>
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
            {part.bbox_mm.size.map((v) => Number(v.toPrecision(4))).join(" × ")} mm · {part.faces.length} faces.
            STL files carry no units: check the size.
          </p>

          <h2>Supports and loads</h2>
          <div className="roles">
            <div className={`role-card fixed ${active === "fixed" ? "on" : ""}`} onClick={() => setActive("fixed")}>
              <div className="role-title"><span className="dot fixed" /> Fixed support</div>
              {chips(fixed, (f) => setFixed((fs) => fs.filter((x) => x !== f)))}
            </div>

            {loads.map((l, i) => {
              const f = forceOf(l);
              const unitLabel = KINDS.find((k) => k[0] === l.kind)![2];
              return (
                <div key={i} className={`role-card load ${active === i ? "on" : ""}`} onClick={() => setActive(i)}>
                  <div className="role-title">
                    <span className="dot load" /> Load {i + 1}
                    {loads.length > 1 && (
                      <button className="x" title="Remove load" onClick={(e) => {
                        e.stopPropagation(); setLoads((ls) => ls.filter((_, j) => j !== i)); setActive("fixed");
                      }}>×</button>
                    )}
                  </div>
                  {chips(l.faces, (x) => update(i, { faces: l.faces.filter((y) => y !== x) }))}
                  <div className="load-grid">
                    <select value={l.kind} onChange={(e) => {
                      const kind = e.target.value as Kind;
                      update(i, { kind, direction: kind === "mass" ? "-z" : l.direction });
                    }}>
                      {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                    <div className="with-unit">
                      <input type="number" min={0} step="any" value={l.value}
                        onChange={(e) => update(i, { value: Number(e.target.value) })} />
                      <em>{unitLabel}</em>
                    </div>
                    {l.kind !== "pressure" ? (
                      <select className="span2" value={l.direction}
                        onChange={(e) => update(i, { direction: e.target.value as Direction })}>
                        {DIRECTIONS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                      </select>
                    ) : <p className="span2 muted">Acts perpendicular to the face, pressing into it.</p>}
                    {l.kind !== "pressure" && l.direction === "custom" && (
                      <div className="span2 vec">
                        {(["X", "Y", "Z"] as const).map((ax, k) => (
                          <label key={ax}>{ax}
                            <input type="number" step="any" value={l.custom[k]} onChange={(e) => {
                              const c = [...l.custom] as Vec3;
                              c[k] = Number(e.target.value);
                              update(i, { custom: c });
                            }} />
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="resolved">
                    {f ? <>= <b>{fmtN(Math.hypot(...f))}</b> along <b>{directionName(unit(f))}</b>
                      {l.faces.length > 0 && <> spread over {l.faces.length} face{l.faces.length > 1 ? "s" : ""}</>}</>
                      : "Pick at least one face and a value above zero."}
                  </div>
                </div>
              );
            })}
            <button className="add" onClick={() => { setLoads((ls) => [...ls, newLoad()]); setActive(loads.length); }}>
              + Add another load
            </button>
          </div>

          <div className="form">
            <MaterialButton materials={materials} value={material} onChange={setMaterial} />
            <label className="row"><span>Mesh</span>
              <select value={mesh} onChange={(e) => setMesh(e.target.value as MeshLevel)}>
                <option value="coarse">Coarse (fastest)</option>
                <option value="medium">Medium</option>
                <option value="fine">Fine (most accurate)</option>
              </select>
            </label>
          </div>
          <button className="primary" disabled={!ready || busy} onClick={submit}>
            {busy ? "Simulating…" : ready ? "Simulate my part" : "Pick a fixed face and a loaded face"}
          </button>
        </>
      )}
      {stageView}
      {!part && stage && createPortal(
        <div className={`drop-stage ${dragging ? "drag" : ""}`} {...dropProps}>
          <div>
            <b>Drop an STL or STEP file anywhere here</b>
            <p>Then click the faces that are held fixed and the faces that carry the load.</p>
          </div>
        </div>,
        stage,
      )}
    </div>
  );
}
