import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";

const navCls = ({ isActive }: { isActive: boolean }) =>
  [
    "block rounded-lg px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-white text-ink shadow-sm"
      : "text-ink-muted hover:bg-white/60 hover:text-ink",
  ].join(" ");

export function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col border-r border-black/5 bg-surface-sidebar px-3 py-4">
        <div className="mb-6 px-2">
          <div className="font-semibold text-ink">Notebook</div>
          <div className="text-xs text-ink-muted">PDF Pipeline</div>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          <NavLink to="/" end className={navCls}>
            Home
          </NavLink>
          <NavLink to="/report" className={navCls}>
            New report
          </NavLink>
          <NavLink to="/chat" className={navCls}>
            Chat
          </NavLink>
          <NavLink to="/settings" className={navCls}>
            Settings
          </NavLink>
        </nav>
        <div className="mt-auto border-t border-black/5 pt-3">
          <div
            className="truncate px-2 text-xs text-ink-muted"
            title={user?.email}
          >
            {user?.email}
          </div>
          <button
            type="button"
            onClick={() => logout()}
            className="mt-2 w-full rounded-lg px-3 py-2 text-left text-sm text-ink-muted hover:bg-white/80 hover:text-ink"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="min-h-screen flex-1 overflow-auto bg-surface p-6">
        <Outlet />
      </main>
    </div>
  );
}
