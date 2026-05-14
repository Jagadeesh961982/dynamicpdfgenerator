import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Eye, EyeOff, Loader2, Sparkles, FileText, Zap, Shield } from "lucide-react";
import toast from "react-hot-toast";
import { loginUser } from "@/api/client";
import { useAuth } from "@/context/AuthContext";

export function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [pending, setPending]   = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    try {
      const res = await loginUser({ email, password });
      await login(res.access_token);
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-bg-page">
      {/* Left branding panel */}
      <div className="hidden lg:flex flex-col justify-between w-[420px] flex-shrink-0 bg-bg-surface border-r border-border p-10">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-900/40">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold gradient-text">DocuMind</span>
        </div>

        <div className="space-y-8">
          <div>
            <h2 className="text-3xl font-bold text-txt-primary leading-tight">
              Turn raw data into<br />
              <span className="gradient-text">executive reports</span>
            </h2>
            <p className="mt-3 text-txt-muted text-sm leading-relaxed">
              Our multi-agent AI pipeline analyzes your data, plans a narrative, and generates stunning PDF presentations — automatically.
            </p>
          </div>

          {[
            { icon: FileText, text: "Supports .txt, .csv, .pdf and JSON input" },
            { icon: Zap,      text: "12-slide reports in minutes, not hours" },
            { icon: Shield,   text: "Your API keys encrypted at rest" },
          ].map(({ icon: Icon, text }) => (
            <div key={text} className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-brand-soft flex items-center justify-center flex-shrink-0 mt-0.5">
                <Icon className="w-4 h-4 text-brand-light" />
              </div>
              <p className="text-sm text-txt-muted leading-relaxed">{text}</p>
            </div>
          ))}
        </div>

        <p className="text-xs text-txt-subtle">© 2025 DocuMind AI Pipeline</p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="mb-8">
            <div className="lg:hidden flex items-center gap-2 mb-6">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              <span className="font-bold gradient-text">DocuMind</span>
            </div>
            <h1 className="text-2xl font-bold text-txt-primary">Welcome back</h1>
            <p className="mt-1.5 text-sm text-txt-muted">Sign in to your account to continue.</p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label className="label" htmlFor="email">Email address</label>
              <input
                id="email" type="email" autoComplete="email" required
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="input" placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="label" htmlFor="password">Password</label>
              <div className="relative">
                <input
                  id="password" type={showPw ? "text" : "password"}
                  autoComplete="current-password" required
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="input pr-10" placeholder="••••••••"
                />
                <button
                  type="button" onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-txt-subtle hover:text-txt-muted transition-colors"
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={pending} className="btn-primary w-full justify-center py-2.5">
              {pending ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in…</> : "Sign in"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-txt-muted">
            Don't have an account?{" "}
            <Link to="/register" className="text-brand-light hover:text-brand font-medium transition-colors">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
