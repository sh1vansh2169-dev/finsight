import { NavLink, Navigate, Outlet, useLocation } from "react-router";

import { useHealth, useMe } from "../api/hooks";
import { Icon } from "./Icon";
import { Loading, SampleBanner } from "./ui";

export const NAV = [
  { to: "/", label: "Home", icon: "home" },
  { to: "/transactions", label: "Transactions", icon: "list" },
  { to: "/money-majra", label: "Money Majra", icon: "people" },
  { to: "/insights", label: "Insights", icon: "insights" },
  { to: "/profile", label: "Profile", icon: "profile" },
] as const;

/** Signed-in layout: sidebar on wide screens, tab bar at the bottom on phones. */
export function AppShell() {
  const me = useMe();
  const health = useHealth();
  const location = useLocation();

  if (me.isPending) return <div className="p-6"><Loading label="Opening MoneyOS" /></div>;
  if (!me.data) return <Navigate to={`/sign-in?next=${encodeURIComponent(location.pathname)}`} replace />;

  return (
    <div className="min-h-screen">
      {health.data?.sample_data && <SampleBanner />}
      <div className="mx-auto flex max-w-6xl">
        <nav aria-label="Main" className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-1 p-4 md:flex">
          <p className="mb-6 px-3 text-lg font-semibold text-primary-ink">MoneyOS</p>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-primary-soft text-primary-ink" : "text-ink-2 hover:bg-surface-2"}`}>
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1 px-4 pb-28 pt-6 md:px-8 md:pb-10">
          <Outlet />
        </main>
      </div>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-5 border-t border-line bg-surface md:hidden">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"}
            className={({ isActive }) =>
              `flex flex-col items-center gap-1 py-2 text-[11px] font-medium ${isActive ? "text-primary-ink" : "text-muted"}`}>
            <Icon name={item.icon} />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function PageTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}
