import type { Material } from "./types";

const num = (v: number | null | undefined, unit = "", digits = 3) =>
  v === null || v === undefined ? "—" : `${Number(v.toPrecision(digits)).toLocaleString("en-US")}${unit}`;

const resistivity = (m: Material) =>
  m.electrical === "not_insulating" ? "not a reliable insulator"
    : m.resistivity === null ? "—"
    : m.electrical === "conductor" ? `${m.resistivity.toExponential(2)} Ω·m`
    : `~10^${Math.round(Math.log10(m.resistivity))} Ω·m (insulator)`;

/** Property sheet of the selected material, with its source. */
export function MaterialCard({ material: m, open = false }: { material: Material; open?: boolean }) {
  const printed = m.category === "printing_polymer";
  const rows: [string, string][] = [
    ["Young's modulus", printed
      ? `${num(m.youngs_modulus, " MPa")} (XY) · ${num(m.youngs_modulus_z, " MPa")} (Z)`
      : num(m.youngs_modulus, " MPa")],
    ...(m.yield_strength ? [["Yield strength", num(m.yield_strength, " MPa")] as [string, string]] : []),
    ["Tensile strength", printed
      ? `${num(m.tensile_strength, " MPa")} (XY) · ${num(m.tensile_strength_z, " MPa")} (Z)`
      : num(m.tensile_strength, " MPa")],
    ["Elongation", num(m.elongation_pct, " %")],
    ["Poisson's ratio", num(m.poisson_ratio)],
    ["Density", num(m.density, " kg/m³", 4)],
    ["Thermal conductivity", num(m.thermal_conductivity, " W/m·K")],
    ["Specific heat", num(m.specific_heat, " J/kg·K")],
    ["Thermal expansion", num(m.thermal_expansion, " µm/m·K")],
    ["Max service temp.", num(m.max_service_temp, " °C")],
    ["Electrical", resistivity(m)],
  ];
  return (
    <details className="material" open={open}>
      <summary>{m.name}{m.condition ? ` · ${m.condition}` : ""}</summary>
      <table>
        <tbody>
          {rows.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}
        </tbody>
      </table>
      {m.notes && <p className="hint">{m.notes}</p>}
      <p className="source">Source: {m.source}</p>
    </details>
  );
}
