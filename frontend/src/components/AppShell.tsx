import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, FilePlus, MessageSquare, Settings,
  LogOut, ChevronLeft, ChevronRight, Sparkles,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV = [
  { to: "/",         icon: LayoutDashboard, label: "Dashboard" },
  { to: "/report",   icon: FilePlus,        label: "New Report" },
  { to: "/chat",     icon: MessageSquare,   label: "AI Chat" },
  { to: "/settings", icon: Settings,        label: "Settings" },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);

  function handleLogout() { logout(); navigate("/login"); }

  const w = collapsed ? "w-16" : "w-56";

  return (
    <div className="flex h-screen bg-bg-page overflow-hidden">
      {/* Sidebar */}
      <aside className={`relative flex flex-col flex-shrink-0 bg-bg-surface border-r border-border transition-all duration-300 ${w}`}>

        {/* Brand */}
        <div className={`flex items-center gap-3 px-4 py-5 border-b border-border ${collapsed ? "justify-center px-0" : ""}`}>
          <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-900/40">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <div>
              <p className="text-sm font-bold gradient-text leading-none">DocuMind</p>
              <p className="text-[10px] text-txt-subtle mt-0.5">AI Report Generator</p>
            </div>
          )}
        </div>

        {/* Nav links */}
        <nav className="flex-1 py-4 px-2 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150
                ${collapsed ? "justify-center" : ""}
                ${isActive
                  ? "bg-brand-soft text-brand-light shadow-sm"
                  : "text-txt-muted hover:text-txt-primary hover:bg-bg-hover"
                }`
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User */}
        <div className="border-t border-border p-3">
          {!collapsed ? (
            <div className="flex items-center gap-2.5 p-2 rounded-lg">
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center flex-shrink-0">
                <span className="text-xs font-bold text-white">
                  {user?.email?.[0]?.toUpperCase() ?? "?"}
                </span>
              </div>
              <p className="flex-1 min-w-0 text-xs text-txt-muted truncate">{user?.email}</p>
              <button
                onClick={handleLogout}
                className="p-1 text-txt-subtle hover:text-err transition-colors rounded"
                title="Sign out"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={handleLogout}
              className="w-full flex justify-center p-2 text-txt-subtle hover:text-err transition-colors rounded-lg"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-3 top-16 w-6 h-6 rounded-full bg-bg-elevated border border-border flex items-center justify-center text-txt-subtle hover:text-txt-primary transition-colors z-10"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
        </button>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
