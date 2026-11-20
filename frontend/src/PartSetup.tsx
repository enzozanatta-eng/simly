import { useCallback, useState } from "react";
import { api, ApiError } from "./api";
import { MaterialCard } from "./MaterialCard";
import { PickViewer, ROLE_COLORS } from "./PickViewer";
import { MaterialSelect } from "./StudyForm";
import type { CustomSpec, Material, MeshLevel, PartFace, PartInfo, Units } from "./types";

type Direction = "-z" | "+z" | "-x" | "+x" | "-y" | "+y" | "push" | "pull";

interface LoadDraft {
  faces: number[];
  newtons: number;
  direction: Direction;
}

const DIRECTIONS: [Direction, string][] = [
  ["-z", "Down (−Z, like weight)"], ["+z", "Up (+Z)"],
  ["+x", "+X"], ["-x", "−X"], ["+y", "+Y"], ["-y", "−Y"],
  ["push", "Push into the face"], ["pull", "Pull out of the face"],
];

const AXIS: Record<string, [number, number, number]> = {
  "-z": [0, 0, -1], "+z": [0, 0, 1], "-x": [-1, 0, 0], "+x": [1, 0, 0],
  "-y": [0, -1, 0], "+y": [0, 1, 0],
};

/** Area-weighted outward normal of a set of faces (the server orients each face outwards). */
function outwardNormal(faces: PartFace[]): [number, number, number] {
  const n = [0, 0, 0];
  for (const f of faces) for (let i = 0; i < 3; i++) n[i] += f.normal[i] * f.area_mm2;
  const len = Math.hypot(n[0], n[1], n[2]) || 1;
  return [n[0] / len, n[1] / len, n[2] / len];
}

interface Props {
  materials: Record<string, Material>;
  busy: boolean;
  onSimulate: (spec: CustomSpec) => void;
}

/** Upload a part, click its faces to fix and load it, then simulate. */
export function PartSetup({ materials, busy, onSimulate }: Props) {
  const [part, setPart] = useState<PartInfo | null>(null);
  const [units, setUnits] = useState<Units>("mm");
  const [fixed, setFixed] = useState<number[]>([]);
  const [loads, setLoads] = useState<LoadDraft[]>([{ faces: [], newtons: 50, direction: "-z" }]);
  const [active, setActive] = useState<"fixed" | number>("fixed");
  const [material, setMaterial] = useState("pla");
  const [mesh, setMesh] = useState<MeshLevel>("medium");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  async function upload(file: File) {
    setUploading(true);
    setError("");
    try {
      setPart(await api.uploadPart(file, units));
      setFixed([]);
      setLoads([{ faces: [], newtons: 50, direction: "-z" }]);
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

  const toggle = (list: number[], f: number) =>
    list.includes(f) ? list.filter((x) => x !== f) : [...list, f];

  function pick(face: number) {
    if (active === "fixed") {
      setFixed((fs) => toggle(fs, face));
      setLoads((ls) => ls.map((l) => ({ ...l, faces: l.faces.filter((x) => x !== face) })));
    } else {
      setLoads((ls) => ls.map((l, i) => (i === active ? { ...l, faces: toggle(l.faces, face) } : l)));
      setFixed((fs) => fs.filter((x) => x !== face));
    }
  }

  const colorOf = useCallback((face: number) => {
    if (fixed.includes(face)) return ROLE_COLORS.fixed;
    const i = loads.findIndex((l) => l.faces.includes(face));
    if (i >= 0) return i === active ? ROLE_COLORS.activeLoad : ROLE_COLORS.load;
    return ROLE_COLORS.none;
  }, [fixed, loads, active]);

  function forceVector(l: LoadDraft): [number, number, number] {
    let dir = AXIS[l.direction];
    if (!dir && part) {
      const n = outwardNormal(part.faces.filter((f) => l.faces.includes(f.id)));
      dir = l.direction === "pull" ? n : [-n[0], -n[1], -n[2]];
    }
    return [dir[0] * l.newtons, dir[1] * l.newtons, dir[2] * l.newtons];
  }

  const ready = part && fixed.length > 0 && loads.every((l) => l.faces.length > 0 && l.newtons > 0);

  function submit() {
    if (!part || !ready) return;
    onSimulate({
      template: "custom_part", part_id: part.part_id, units, fixed_faces: fixed,
      loads: loads.map((l) => ({ faces: l.faces, force: forceVector(l) })), material, mesh,
    });
  }

  return (
    <div className="part-setup">
      <label className="upload">
        <input type="file" accept=".stl,.step,.stp" disabled={uploading}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <span>{uploading ? "Reading the part…" : part ? "Upload another part" : "Upload your part (STL or STEP)"}</span>
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
            Size {part.bbox_mm.size.map((v) => Number(v.toPrecision(4))).join(" × ")} mm ·{" "}
            {part.faces.length} faces. Check the size: STL files carry no units.
          </p>
          <div className="pick-wrap">
            <PickViewer part={part} colorOf={colorOf} onPick={pick} />
            <div className="overlay">
              {active === "fixed" ? "Click the faces that are held fixed" : `Click the faces where load ${active + 1} acts`}
            </div>
          </div>

          <div className="roles">
            <button className={active === "fixed" ? "role on fixed" : "role fixed"} onClick={() => setActive("fixed")}>
              Fixed support · {fixed.length} face{fixed.length === 1 ? "" : "s"}
            </button>
            {loads.map((l, i) => (
              <div key={i} className={active === i ? "load on" : "load"} onClick={() => setActive(i)}>
                <b>Load {i + 1}</b> · {l.faces.length} face{l.faces.length === 1 ? "" : "s"}
                <div className="load-row">
                  <input type="number" min={0} value={l.newtons}
                    onChange={(e) => setLoads((ls) => ls.map((x, j) => j === i ? { ...x, newtons: Number(e.target.value) } : x))} />
                  <em>N</em>
                  <select value={l.direction}
                    onChange={(e) => setLoads((ls) => ls.map((x, j) => j === i ? { ...x, direction: e.target.value as Direction } : x))}>
                    {DIRECTIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  {loads.length > 1 && (
                    <button className="x" title="Remove load"
                      onClick={(e) => { e.stopPropagation(); setLoads((ls) => ls.filter((_, j) => j !== i)); setActive("fixed"); }}>×</button>
                  )}
                </div>
              </div>
            ))}
            <button className="add" onClick={() => { setLoads((ls) => [...ls, { faces: [], newtons: 50, direction: "-z" }]); setActive(loads.length); }}>
              + Add another load
            </button>
            <p className="hint">Tip: 1 kg of weight ≈ 9.81 N.</p>
          </div>

          <div className="form">
            <label className="row"><span>Material</span>
              <MaterialSelect materials={materials} value={material} onChange={setMaterial} />
            </label>
            {materials[material] && <MaterialCard material={materials[material]} />}
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
    </div>
  );
}
