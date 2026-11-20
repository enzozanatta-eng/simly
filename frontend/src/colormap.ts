/**
 * Turbo colormap (Google, 2019), polynomial approximation by Mikhailov.
 * Perceptually smoother than "jet" while keeping the familiar blue-to-red read.
 */
export function turbo(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t));
  const r = 0.13572138 + x * (4.6153926 + x * (-42.66032258 + x * (132.13108234 +
    x * (-152.94239396 + x * 59.28637943))));
  const g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 +
    x * (4.27729857 + x * 2.82956604))));
  const b = 0.1066733 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 +
    x * (-89.90310912 + x * 27.34824973))));
  const c = (v: number) => Math.min(1, Math.max(0, v));
  return [c(r), c(g), c(b)];
}

export function cssColor(t: number): string {
  const [r, g, b] = turbo(t).map((v) => Math.round(v * 255));
  return `rgb(${r}, ${g}, ${b})`;
}
