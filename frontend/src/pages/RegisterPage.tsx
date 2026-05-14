import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Eye, EyeOff, Loader2, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { loginUser, registerUser } from "@/api/client";
import { useAuth } from "@/context/AuthContext";

export function RegisterPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [pending, setPending]   = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) { toast.error("Password must be at least 8 characters"); return; }
    setPending(true);
    try {
      await registerUser({ email, password });
      const res = await loginUser({ email, password });
      await login(res.access_token);
      toast.success("Account created successfully!");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-page px-6 py-12">
      <div className="w-full max-w-sm animate-fade-in">
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-900/40">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold gradient-text">DocuMind</span>
        </div>

        <div className="mb-8">
          <h1 className="text-2xl font-bold text-txt-primary">Create account</h1>
          <p className="mt-1.5 text-sm text-txt-muted">Start generating AI-powered reports today.</p>
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
                autoComplete="new-password" required minLength={8}
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="input pr-10" placeholder="Min. 8 characters"
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
            {pending ? <><Loader2 className="w-4 h-4 animate-spin" /> Creating account…</> : "Create account"}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-txt-muted">
          Already have an account?{" "}
          <Link to="/login" className="text-brand-light hover:text-brand font-medium transition-colors">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
