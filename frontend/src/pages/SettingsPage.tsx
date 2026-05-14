import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  User, Key, Settings2, Trash2, Plus, Loader2, CheckCircle2,
  Eye, EyeOff, ShieldCheck, Sparkles, AlertTriangle, RefreshCw,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  cleanupJobs, createKey, deleteKey, getPreferences, listKeys, putPreferences,
} from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import type { LLMKeyCreate, PreferencesBody, Provider, VisualStyle } from "@/api/types";

function SectionCard({ title, icon: Icon, children }: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border">
        <div className="w-7 h-7 rounded-lg bg-brand-soft flex items-center justify-center flex-shrink-0">
          <Icon className="w-3.5 h-3.5 text-brand-light" />
        </div>
        <h2 className="text-sm font-semibold text-txt-primary">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();

  // ── Preferences ──────────────────────────────────────────────────
  const { data: prefs, isLoading: prefsLoading } = useQuery({
    queryKey: ["prefs"],
    queryFn: getPreferences,
  });

  const [provider, setProvider] = useState<Provider>("openrouter");
  const [modelAll, setModelAll] = useState("");
  const [style, setStyle] = useState<VisualStyle>("auto");
  const [iterations, setIterations] = useState(3);
  const [threshold, setThreshold] = useState(7.5);
  const [maxChars, setMaxChars] = useState(120000);
  const [prefsDirty, setPrefsDirty] = useState(false);

  useEffect(() => {
    if (!prefs) return;
    const s = prefs.settings as Record<string, unknown>;
    setProvider((s.provider as Provider) ?? "openrouter");
    setModelAll((s.model_all as string) ?? "");
    setStyle((s.visual_style as VisualStyle) ?? "auto");
    setIterations((s.max_iterations as number) ?? 3);
    setThreshold((s.pass_threshold as number) ?? 7.5);
    setMaxChars((s.max_data_chars as number) ?? 120000);
    setPrefsDirty(false);
  }, [prefs]);

  const prefsMut = useMutation({
    mutationFn: (body: PreferencesBody) => putPreferences(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prefs"] });
      setPrefsDirty(false);
      toast.success("Preferences saved");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
  });

  function handleSavePrefs() {
    prefsMut.mutate({
      provider,
      model_all: modelAll || null,
      visual_style: style,
      max_iterations: iterations,
      pass_threshold: threshold,
      max_data_chars: maxChars,
    });
  }

  // ── LLM Keys ─────────────────────────────────────────────────────
  const { data: keys = [], isLoading: keysLoading } = useQuery({
    queryKey: ["llm-keys"],
    queryFn: listKeys,
  });

  const [showAddKey, setShowAddKey] = useState(false);
  const [keyProvider, setKeyProvider] = useState<Provider>("openrouter");
  const [keyLabel, setKeyLabel] = useState("");
  const [keyValue, setKeyValue] = useState("");
  const [showKeyValue, setShowKeyValue] = useState(false);

  const addKeyMut = useMutation({
    mutationFn: (body: LLMKeyCreate) => createKey(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-keys"] });
      setShowAddKey(false);
      setKeyLabel("");
      setKeyValue("");
      setShowKeyValue(false);
      toast.success("API key added");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed to add key"),
  });

  const delKeyMut = useMutation({
    mutationFn: (id: string) => deleteKey(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["llm-keys"] }); toast.success("Key deleted"); },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  // ── Cleanup ───────────────────────────────────────────────────────
  const [cleanupDays, setCleanupDays] = useState(30);
  const cleanupMut = useMutation({
    mutationFn: () => cleanupJobs(cleanupDays, false),
    onSuccess: ({ deleted_jobs }) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["admin-stats"] });
      toast.success(`Deleted ${deleted_jobs} old job${deleted_jobs !== 1 ? "s" : ""}`);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Cleanup failed"),
  });

  function fmtDate(iso: string) {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  }

  function mark() { setPrefsDirty(true); }

  return (
    <div className="p-6 max-w-3xl mx-auto animate-fade-in space-y-5">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-lg bg-brand-soft flex items-center justify-center">
          <Settings2 className="w-3.5 h-3.5 text-brand-light" />
        </div>
        <h1 className="text-xl font-bold text-txt-primary">Settings</h1>
      </div>

      {/* Profile */}
      <SectionCard title="Profile" icon={User}>
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white font-bold text-lg flex-shrink-0">
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </div>
          <div>
            <p className="text-sm font-medium text-txt-primary">{user?.email}</p>
            {user?.created_at && (
              <p className="text-xs text-txt-subtle mt-0.5">Member since {fmtDate(user.created_at)}</p>
            )}
            <span className="inline-flex items-center gap-1 mt-1.5 text-[10px] text-ok bg-ok-soft px-2 py-0.5 rounded-full">
              <CheckCircle2 className="w-2.5 h-2.5" /> Active account
            </span>
          </div>
        </div>
      </SectionCard>

      {/* Pipeline Defaults */}
      <SectionCard title="Pipeline Defaults" icon={Sparkles}>
        {prefsLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-brand" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Default Provider</label>
                <select value={provider} onChange={(e) => { setProvider(e.target.value as Provider); mark(); }} className="select">
                  <option value="openrouter">OpenRouter</option>
                  <option value="gemini">Gemini</option>
                  <option value="nvidia">NVIDIA</option>
                </select>
              </div>
              <div>
                <label className="label">Default Model</label>
                <input value={modelAll} onChange={(e) => { setModelAll(e.target.value); mark(); }} className="input" placeholder="google/gemini-3.1-flash-lite-preview" />
              </div>
              <div>
                <label className="label">Visual Style</label>
                <select value={style} onChange={(e) => { setStyle(e.target.value as VisualStyle); mark(); }} className="select">
                  <option value="auto">Auto (AI picks)</option>
                  <option value="notebooklm">NotebookLM</option>
                  <option value="modern">Modern</option>
                  <option value="dark">Dark</option>
                </select>
              </div>
              <div>
                <label className="label">Max Iterations (1–5)</label>
                <input type="number" min={1} max={5} value={iterations} onChange={(e) => { setIterations(+e.target.value); mark(); }} className="input" />
              </div>
              <div>
                <label className="label">Pass Threshold (0–10)</label>
                <input type="number" min={0} max={10} step={0.5} value={threshold} onChange={(e) => { setThreshold(+e.target.value); mark(); }} className="input" />
              </div>
              <div>
                <label className="label">Max Data Chars</label>
                <input type="number" min={10000} max={500000} step={10000} value={maxChars} onChange={(e) => { setMaxChars(+e.target.value); mark(); }} className="input" />
              </div>
            </div>
            <div className="flex justify-end pt-1">
              <button onClick={handleSavePrefs} disabled={prefsMut.isPending || !prefsDirty} className="btn-primary px-5">
                {prefsMut.isPending
                  ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving…</>
                  : prefsDirty
                    ? <><CheckCircle2 className="w-3.5 h-3.5" /> Save Preferences</>
                    : "Saved"
                }
              </button>
            </div>
          </div>
        )}
      </SectionCard>

      {/* LLM API Keys */}
      <SectionCard title="LLM API Keys" icon={Key}>
        <div className="space-y-3">
          {keysLoading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-brand" /></div>
          ) : keys.length === 0 && !showAddKey ? (
            <div className="text-center py-6">
              <ShieldCheck className="w-8 h-8 text-txt-subtle mx-auto mb-2" />
              <p className="text-sm text-txt-muted">No API keys stored</p>
              <p className="text-xs text-txt-subtle mt-0.5">Keys are encrypted at rest</p>
            </div>
          ) : (
            <div className="divide-y divide-border rounded-lg border border-border overflow-hidden">
              {keys.map((k) => (
                <div key={k.id} className="flex items-center gap-3 px-4 py-3 bg-bg-elevated/30 hover:bg-bg-elevated/60 transition-colors group">
                  <div className="w-7 h-7 rounded-md bg-brand-soft flex items-center justify-center flex-shrink-0">
                    <Key className="w-3 h-3 text-brand-light" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-txt-primary capitalize">{k.provider}</span>
                      {k.label && <span className="text-[10px] text-txt-subtle">· {k.label}</span>}
                    </div>
                    <span className="font-mono text-xs text-txt-subtle bg-bg-elevated px-1.5 py-0.5 rounded">{k.masked_hint}</span>
                  </div>
                  <span className="text-[10px] text-txt-subtle">{new Date(k.created_at).toLocaleDateString()}</span>
                  <button
                    onClick={() => { if (confirm("Delete this key?")) delKeyMut.mutate(k.id); }}
                    disabled={delKeyMut.isPending}
                    className="opacity-0 group-hover:opacity-100 p-1.5 text-txt-subtle hover:text-err rounded transition-all"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {showAddKey ? (
            <div className="border border-border rounded-xl p-4 bg-bg-elevated/20 space-y-3 animate-slide-up">
              <p className="text-xs font-medium text-txt-muted">Add new API key</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Provider</label>
                  <select value={keyProvider} onChange={(e) => setKeyProvider(e.target.value as Provider)} className="select">
                    <option value="openrouter">OpenRouter</option>
                    <option value="gemini">Gemini</option>
                    <option value="nvidia">NVIDIA</option>
                  </select>
                </div>
                <div>
                  <label className="label">Label (optional)</label>
                  <input value={keyLabel} onChange={(e) => setKeyLabel(e.target.value)} className="input" placeholder="e.g. Production" />
                </div>
              </div>
              <div>
                <label className="label">API Key</label>
                <div className="relative">
                  <input
                    type={showKeyValue ? "text" : "password"}
                    value={keyValue}
                    onChange={(e) => setKeyValue(e.target.value)}
                    className="input pr-10 font-mono text-xs"
                    placeholder="sk-or-v1-…"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKeyValue(!showKeyValue)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-txt-subtle hover:text-txt-muted"
                  >
                    {showKeyValue ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowAddKey(false)} className="btn-ghost text-xs px-3 py-1.5">Cancel</button>
                <button
                  onClick={() => addKeyMut.mutate({ provider: keyProvider, api_key: keyValue, label: keyLabel || undefined })}
                  disabled={!keyValue.trim() || addKeyMut.isPending}
                  className="btn-primary text-xs px-3 py-1.5"
                >
                  {addKeyMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : "Add Key"}
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => setShowAddKey(true)} className="flex items-center gap-2 text-xs text-txt-muted hover:text-brand-light transition-colors">
              <Plus className="w-3.5 h-3.5" />
              Add API key
            </button>
          )}
        </div>
      </SectionCard>

      {/* Maintenance */}
      <SectionCard title="Maintenance" icon={RefreshCw}>
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-warn-soft border border-warn/20">
            <AlertTriangle className="w-4 h-4 text-warn mt-0.5 flex-shrink-0" />
            <p className="text-xs text-txt-muted leading-relaxed">
              Cleanup permanently deletes completed and failed jobs older than the selected number of days. This action cannot be undone.
            </p>
          </div>
          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="label">Delete jobs older than</label>
              <div className="flex items-center gap-2">
                <input type="number" min={1} max={365} value={cleanupDays} onChange={(e) => setCleanupDays(+e.target.value)} className="input w-24" />
                <span className="text-sm text-txt-muted">days</span>
              </div>
            </div>
            <button
              onClick={() => { if (confirm(`Delete all jobs older than ${cleanupDays} days?`)) cleanupMut.mutate(); }}
              disabled={cleanupMut.isPending}
              className="btn-danger px-4 py-2"
            >
              {cleanupMut.isPending
                ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Cleaning…</>
                : <><Trash2 className="w-3.5 h-3.5" /> Run Cleanup</>
              }
            </button>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
