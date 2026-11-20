/**
 * Simly mark: a cantilever beam bending under a load, coloured by its own
 * stress (hot at the clamp, cool at the tip), which is the first thing the app shows.
 */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="simly-stress" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#ff6b35" />
          <stop offset="0.5" stopColor="#ffd43b" />
          <stop offset="1" stopColor="#3bc9db" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill="#121a3a" />
      <rect x="10" y="12" width="6" height="40" rx="2" fill="#8d99ae" />
      <path d="M16 25 C29 25 40 28 50 37" stroke="url(#simly-stress)" strokeWidth="8"
        strokeLinecap="round" fill="none" />
      <path d="M50 44 v8 M46.5 48.5 L50 52.5 L53.5 48.5" stroke="white" strokeWidth="3"
        strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
