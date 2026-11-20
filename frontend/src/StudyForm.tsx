import { MaterialCard } from "./MaterialCard";
import type { Material, Spec, TemplateName } from "./types";

interface Field {
  key: string;
  label: string;
  unit: string;
}

export const TEMPLATES: Record<TemplateName, { title: string; fields: Field[]; example: Spec }> = {
  cantilever_beam: {
    title: "Cantilever beam",
    fields: [
      { key: "length", label: "Length", unit: "mm" },
      { key: "width", label: "Width", unit: "mm" },
      { key: "height", label: "Height", unit: "mm" },
      { key: "load", label: "Tip load", unit: "N" },
    ],
    example: {
      template: "cantilever_beam", length: 1000, width: 50, height: 80, load: 1000,
      material: "steel", mesh: "medium",
    },
  },
  plate_with_hole: {
    title: "Plate with a hole",
    fields: [
      { key: "length", label: "Length", unit: "mm" },
      { key: "width", label: "Width", unit: "mm" },
      { key: "thickness", label: "Thickness", unit: "mm" },
      { key: "hole_diameter", label: "Hole diameter", unit: "mm" },
      { key: "load", label: "Tensile force", unit: "N" },
    ],
    example: {
      template: "plate_with_hole", length: 200, width: 100, thickness: 5,
      hole_diameter: 30, load: 10000, material: "steel", mesh: "medium",
    },
  },
};

const GROUPS: [Material["category"], string][] = [
  ["printing_polymer", "3D printing filaments"],
  ["metal", "Metals"],
  ["engineering_polymer", "Engineering plastics"],
];

interface Props {
  spec: Spec;
  materials: Record<string, Material>;
  onChange: (spec: Spec) => void;
}

/** Material dropdown grouped by family. */
export function MaterialSelect({ materials, value, onChange }: {
  materials: Record<string, Material>;
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {GROUPS.map(([cat, label]) => (
        <optgroup key={cat} label={label}>
          {Object.values(materials).filter((m) => m.category === cat).map((m) => (
            <option key={m.key} value={m.key}>{m.name}</option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

/** Editable study parameters: the AI fills them in, the user can adjust any of them. */
export function StudyForm({ spec, materials, onChange }: Props) {
  const t = TEMPLATES[spec.template];
  const set = (key: string, value: string | number) => onChange({ ...spec, [key]: value });

  return (
    <div className="form">
      <label className="row">
        <span>Study</span>
        <select
          value={spec.template}
          onChange={(e) => onChange({ ...TEMPLATES[e.target.value as TemplateName].example })}
        >
          {Object.entries(TEMPLATES).map(([k, v]) => <option key={k} value={k}>{v.title}</option>)}
        </select>
      </label>
      {t.fields.map((f) => (
        <label className="row" key={f.key}>
          <span>{f.label}</span>
          <input
            type="number"
            min={0}
            value={spec[f.key] ?? ""}
            onChange={(e) => set(f.key, e.target.value === "" ? "" : Number(e.target.value))}
          />
          <em>{f.unit}</em>
        </label>
      ))}
      <label className="row">
        <span>Material</span>
        <MaterialSelect materials={materials} value={String(spec.material)}
          onChange={(k) => set("material", k)} />
      </label>
      {materials[spec.material] && <MaterialCard material={materials[spec.material]} />}
      <label className="row">
        <span>Mesh</span>
        <select value={spec.mesh} onChange={(e) => set("mesh", e.target.value)}>
          <option value="coarse">Coarse (fastest)</option>
          <option value="medium">Medium</option>
          <option value="fine">Fine (most accurate)</option>
        </select>
      </label>
    </div>
  );
}
