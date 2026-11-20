import { cssColor } from "./colormap";
import type { StudyResult } from "./types";

const fmt = (v: number, digits = 4) =>
  Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0)
    ? v.toExponential(2)
    : Number(v.toPrecision(digits)).toLocaleString("en-US", { maximumFractionDigits: 6 });

export function Legend({ range }: { range: [number, number] }) {
  const stops = Array.from({ length: 11 }, (_, i) => cssColor(i / 10)).join(", ");
  return (
    <div className="legend">
      <span>von Mises stress (MPa)</span>
      <div className="bar" style={{ background: `linear-gradient(to right, ${stops})` }} />
      <div className="ticks"><span>{fmt(range[0], 3)}</span><span>{fmt(range[1], 3)}</span></div>
    </div>
  );
}

export function Results({ result }: { result: StudyResult }) {
  const s = result.summary;
  const cls = (v: number) => (v >= 2 ? "good" : v >= 1 ? "warn" : "bad");
  const conv = result.convergence;
  const printed = s.safety_factor_z !== undefined;

  return (
    <div className="results">
      <div className={`cards ${printed ? "four" : ""}`}>
        <div className="card">
          <small>Peak von Mises stress</small>
          <strong>{fmt(s.max_von_mises_MPa)} MPa</strong>
        </div>
        <div className="card">
          <small>Max displacement</small>
          <strong>{fmt(s.max_displacement_mm)} mm</strong>
        </div>
        <div className={`card ${cls(s.safety_factor)}`}>
          <small>Safety factor{printed ? " in-layer (XY)" : ""} vs {s.strength_basis} ({fmt(s.strength_MPa, 3)} MPa)</small>
          <strong>{fmt(s.safety_factor, 3)}</strong>
        </div>
        {printed && (
          <div className={`card ${cls(s.safety_factor_z!)}`}>
            <small>Safety factor across layers (Z, {fmt(s.strength_z_MPa!, 3)} MPa)</small>
            <strong>{fmt(s.safety_factor_z!, 3)}</strong>
          </div>
        )}
      </div>
      {s.warnings.length > 0 && (
        <ul className="warnings">{s.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}

      <h3>Checks</h3>
      <table>
        <tbody>
          <tr>
            <td>Force balance (support reactions vs applied loads)</td>
            <td><span className={`badge ${s.equilibrium_error_pct < 0.1 ? "PASS" : "FAIL"}`}>
              {s.equilibrium_error_pct < 0.001 ? "< 0.001" : s.equilibrium_error_pct.toFixed(3)}% off
            </span></td>
          </tr>
        </tbody>
      </table>

      {result.comparisons.length > 0 && (<>
      <h3>Simulation vs hand calculation</h3>
      <table>
        <thead>
          <tr><th>Quantity</th><th>Formula</th><th>Hand calc</th><th>Simulation</th><th>Error</th></tr>
        </thead>
        <tbody>
          {result.comparisons.map((c) => (
            <tr key={c.quantity} title={c.note}>
              <td>{c.quantity}</td>
              <td className="formula">{c.formula}</td>
              <td>{fmt(c.hand_calc)} {c.unit}</td>
              <td>{fmt(c.simulation)} {c.unit}</td>
              <td><span className={`badge ${c.status}`}>{c.error_pct > 0 ? "+" : ""}{c.error_pct.toFixed(2)}%</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.comparisons.filter((c) => c.note).map((c) => (
        <p className="hint" key={c.quantity}><b>{c.quantity}:</b> {c.note}</p>
      ))}
      </>)}

      {conv && (
        <>
          <h3>Mesh convergence (GCI)</h3>
          <table>
            <thead>
              <tr><th>Quantity</th><th>Coarse</th><th>Medium</th><th>Fine</th><th>Uncertainty</th></tr>
            </thead>
            <tbody>
              {conv.quantities.map((q) => (
                <tr key={q.quantity}>
                  <td>{q.quantity}</td>
                  <td>{fmt(q.coarse)}</td>
                  <td>{fmt(q.medium)}</td>
                  <td>{fmt(q.fine)} {q.unit}</td>
                  <td>{q.behaviour === "singular"
                    ? <span className="badge FAIL">does not converge (singularity)</span>
                    : <>± {q.gci_fine_pct.toFixed(2)}% <em>({q.behaviour}{q.observed_order ? `, p = ${q.observed_order}` : ""})</em></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">
            {conv.elements.coarse.toLocaleString()} / {conv.elements.medium.toLocaleString()} /{" "}
            {conv.elements.fine.toLocaleString()} elements. {conv.method}.
          </p>
        </>
      )}

      <p className="hint">{result.note}</p>
      <p className="meta">
        {s.material} · {result.mesh.elements.toLocaleString()} {result.mesh.element_type} elements ·
        mesh {result.timings.mesh_s}s · solve {result.timings.solve_s}s · CalculiX
      </p>
    </div>
  );
}
