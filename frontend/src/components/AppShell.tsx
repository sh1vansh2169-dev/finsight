import { NavLink, Navigate, Outlet, useLocation } from "react-router";

import { useHealth, useMe } from "../api/hooks";
import { useTheme } from "../lib/theme";
import { Icon } from "./Icon";
import { Loading, SampleBanner } from "./ui";

export const NAV = [
  { to: "/", label: "Home", icon: "home" },
  { to: "/transactions", label: "Transactions", icon: "list" },
  { to: "/money-majra", label: "Money Majra", icon: "people" },
  { to: "/insights", label: "Insights", icon: "insights" },
  { to: "/profile", label: "Profile", icon: "profile" },
] as const;

function activeIndex(pathname: string): number {
  const index = NAV.findIndex((item) => item.to !== "/" && pathname.startsWith(item.to));
  return index === -1 ? 0 : index;
}

/** Light/dark switch. Remembered on this device; Profile also offers "follow the system". */
function ThemeButton({ className = "" }: { className?: string }) {
  const [, setTheme] = useTheme();
  const toggle = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  return (
    <button type="button" onClick={toggle} aria-label="Switch between light and dark"
      className={`press glass flex h-11 w-11 items-center justify-center rounded-full text-ink ${className}`}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
    </button>
  );
}

/** Signed-in layout: a frosted sidebar on wide screens; a floating tab bar with a sliding pill on phones. */
export function AppShell() {
  const me = useMe();
  const health = useHealth();
  const location = useLocation();

  if (me.isPending) return <div className="p-6"><Loading label="Opening FinSight" /></div>;
  if (!me.data) return <Navigate to={`/sign-in?next=${encodeURIComponent(location.pathname)}`} replace />;
  const active = activeIndex(location.pathname);

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      {/* Soft colour behind the frosted surfaces; decoration only. */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="glow absolute -left-24 -top-24 h-80 w-80 rounded-full blur-3xl" style={{ background: "var(--glow-a)" }} />
        <div className="glow absolute -right-24 top-1/3 h-72 w-72 rounded-full blur-3xl"
          style={{ background: "var(--glow-b)", animationDelay: "-7s" }} />
      </div>

      {health.data?.sample_data && <SampleBanner />}
      <div className="mx-auto flex max-w-6xl">
        <nav aria-label="Main" className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col p-4 md:flex">
          <div className="glass flex h-full flex-col gap-1 rounded-[var(--radius-card)] p-3">
            <p className="mb-6 px-3 pt-2 text-xl font-light tracking-tight text-ink">Fin<span className="font-semibold text-primary-ink">Sight</span></p>
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === "/"}
                className={({ isActive }) =>
                  `press flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium ${
                    isActive ? "bg-primary text-on-primary shadow-[0_10px_24px_-12px_var(--primary)]" : "text-ink-2 hover:bg-surface-2"}`}>
                <Icon name={item.icon} />
                {item.label}
              </NavLink>
            ))}
            <div className="mt-auto px-1 pb-1"><ThemeButton /></div>
          </div>
        </nav>
        <main className="min-w-0 flex-1 px-4 pb-32 pt-6 md:px-8 md:pb-10">
          <div className="mb-2 flex justify-end md:hidden"><ThemeButton /></div>
          {/* Keyed by the page, so every page glides in when opened. */}
          <div key={location.pathname} className="page-enter">
            <Outlet />
          </div>
        </main>
      </div>

      <nav aria-label="Main" className="glass fixed inset-x-4 bottom-5 z-10 h-16 overflow-hidden rounded-full md:hidden">
        <div aria-hidden="true" className="nav-pill absolute left-2 top-2 h-12 rounded-full bg-primary"
          style={{ width: "calc((100% - 1rem) / 5)", transform: `translateX(${active * 100}%)` }} />
        <div className="relative grid h-full grid-cols-5 px-2">
          {NAV.map((item, i) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}
              className={`press flex items-center justify-center ${i === active ? "text-on-primary" : "text-muted"}`}>
              <Icon name={item.icon} />
              <span className="sr-only">{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export function PageTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-3xl font-light tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}
