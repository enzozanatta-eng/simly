/**
 * Simly mark: one triangle split into four finite elements, coloured like a
 * stress plot (cool to hot). The basic building block of every simulation.
 */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="15" fill="#121a3a" />
      <g stroke="#121a3a" strokeWidth="2.2" strokeLinejoin="round">
        <path d="M32 11 L21.5 30 L42.5 30 Z" fill="#ff6b35" />
        <path d="M21.5 30 L11 49 L32 49 Z" fill="#4c6ef5" />
        <path d="M42.5 30 L32 49 L53 49 Z" fill="#fcc419" />
        <path d="M21.5 30 L42.5 30 L32 49 Z" fill="#22b8cf" />
      </g>
    </svg>
  );
}
