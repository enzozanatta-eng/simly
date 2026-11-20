import { useEffect, useMemo, useState } from "react";
import { MaterialCard } from "./MaterialCard";
import type { Material } from "./types";

type Family = "all" | Material["category"];
type SortKey = "strength" | "stiffness" | "light" | "heat";

const FAMILIES: [Family, string][] = [
  ["all", "All"], ["printing_polymer", "3D printing"], ["metal", "Metals"], ["engineering_polymer", "Plastics"],
];

const SORTS: [SortKey, string][] = [
  ["strength", "Strongest"], ["stiffness", "Stiffest"], ["light", "Lightest"], ["heat", "Most heat resistant"],
];

const FILTERS: { key: string; label: string; test: (m: Material) => boolean }[] = [
  { key: "heat", label: "Above 90 °C", test: (m) => (m.max_service_temp ?? 0) >= 90 },
  { key: "outdoor", label: "Outdoors / UV", test: (m) => /ASA|stainless|aluminium|titanium|PC/i.test(m.name) },
  { key: "flex", label: "Flexible", test: (m) => m.youngs_modulus < 500 },
  { key: "insulator", label: "Electrical insulator", test: (m) => m.electrical === "insulator" },
  { key: "conductor", label: "Conducts electricity", test: (m) => m.electrical === "conductor" },
];

const strength = (m: Material) => m.yield_strength ?? m.tensile_strength;
const SORT_VALUE: Record<SortKey, (m: Material) => number> = {
  strength, stiffness: (m) => m.youngs_modulus, light: (m) => -m.density,
  heat: (m) => m.max_service_temp ?? -1,
};

/** One horizontal bar on a log scale, so plastics and metals both stay readable. */
function Bar({ value, min, max, label }: { value: number; min: number; max: number; label: string }) {
  const t = value > 0 ? (Math.log10(value) - Math.log10(min)) / (Math.log10(max) - Math.log10(min)) : 0;
  return (
    <div className="bar-row">
      <span>{label}</span>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(4, 100 * t)}%` }} /></div>
    </div>
  );
}

const modulus = (mpa: number) =>
  mpa >= 1000 ? `${Number((mpa / 1000).toPrecision(3))} GPa` : `${Number(mpa.toPrecision(3))} MPa`;

interface Props {
  materials: Record<string, Material>;
  value: string;
  onChange: (key: string) => void;
}

/** The current material as a compact card that opens the material browser. */
export function MaterialButton({ materials, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const m = materials[value];
  return (
    <>
      <button className="material-button" onClick={() => setOpen(true)}>
        <div>
          <small>Material</small>
          <b>{m?.name ?? value}</b>
          {m && <span>{m.condition}</span>}
        </div>
        {m && (
          <div className="material-stats">
            <span>{Number(strength(m).toPrecision(3))} MPa<em>{m.yield_strength ? "yield" : "strength"}</em></span>
            <span>{modulus(m.youngs_modulus)}<em>stiffness</em></span>
            <span>{Number((m.density / 1000).toPrecision(3))} g/cm³<em>density</em></span>
          </div>
        )}
        <i>Change</i>
      </button>
      {open && <MaterialBrowser materials={materials} value={value}
        onChange={(k) => { onChange(k); setOpen(false); }} onClose={() => setOpen(false)} />}
    </>
  );
}

function MaterialBrowser({ materials, value, onChange, onClose }: Props & { onClose: () => void }) {
  const all = useMemo(() => Object.values(materials), [materials]);
  const [family, setFamily] = useState<Family>(materials[value]?.category ?? "all");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<string[]>([]);
  const [sort, setSort] = useState<SortKey>("strength");
  const [focus, setFocus] = useState(value);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const range = (f: (m: Material) => number) => {
    const v = all.map(f).filter((x) => x > 0);
    return [Math.min(...v), Math.max(...v)] as const;
  };
  const [sMin, sMax] = range(strength);
  const [eMin, eMax] = range((m) => m.youngs_modulus);

  const shown = all
    .filter((m) => family === "all" || m.category === family)
    .filter((m) => `${m.name} ${m.condition}`.toLowerCase().includes(query.toLowerCase()))
    .filter((m) => filters.every((k) => FILTERS.find((f) => f.key === k)!.test(m)))
    .sort((a, b) => SORT_VALUE[sort](b) - SORT_VALUE[sort](a));

  const focused = materials[focus];

  return (
    <div className="modal-veil" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Choose a material</h3>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <div className="browser-tools">
          <input autoFocus placeholder="Search: PETG, 6061, stainless…" value={query}
            onChange={(e) => setQuery(e.target.value)} />
          <div className="seg">
            {FAMILIES.map(([k, label]) => (
              <button key={k} className={family === k ? "on" : ""} onClick={() => setFamily(k)}>{label}</button>
            ))}
          </div>
          <div className="filter-chips">
            {FILTERS.map((f) => (
              <button key={f.key} className={filters.includes(f.key) ? "on" : ""}
                onClick={() => setFilters((fs) => fs.includes(f.key) ? fs.filter((x) => x !== f.key) : [...fs, f.key])}>
                {f.label}
              </button>
            ))}
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              {SORTS.map(([k, label]) => <option key={k} value={k}>Sort: {label}</option>)}
            </select>
          </div>
        </div>
        <div className="browser-body">
          <ul className="mat-list">
            {shown.length === 0 && <li className="muted">No material matches.</li>}
            {shown.map((m) => (
              <li key={m.key} className={`${focus === m.key ? "focus" : ""} ${value === m.key ? "current" : ""}`}
                onClick={() => setFocus(m.key)} onDoubleClick={() => onChange(m.key)}>
                <div className="mat-name">
                  <b>{m.name}</b>
                  <span>{m.condition}</span>
                </div>
                <div className="mat-bars">
                  <Bar label={`${Number(strength(m).toPrecision(3))} MPa`} value={strength(m)} min={sMin} max={sMax} />
                  <Bar label={modulus(m.youngs_modulus)} value={m.youngs_modulus} min={eMin} max={eMax} />
                </div>
                <div className="mat-temp">{m.max_service_temp ? `${m.max_service_temp} °C` : "—"}</div>
              </li>
            ))}
          </ul>
          <div className="mat-detail">
            {focused && (
              <>
                <MaterialCard material={focused} open />
                <button className="primary" onClick={() => onChange(focused.key)}>
                  {value === focused.key ? "Keep this material" : `Use ${focused.name}`}
                </button>
              </>
            )}
          </div>
        </div>
        <p className="hint legend-note">Bars: strength (top) and stiffness (bottom), log scale. Temperature: max service temperature.
          Double-click a material to pick it.</p>
      </div>
    </div>
  );
}
