import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createKey,
  deleteKey,
  getPreferences,
  listKeys,
  putPreferences,
} from "@/api/client";
import type { AgentModels, Provider, VisualStyle } from "@/api/types";

function parseSettings(raw: Record<string, unknown>): {
  provider: Provider | "";
  modelAll: string;
  agents: AgentModels;
  visualStyle: VisualStyle | "";
  maxIterations: string;
  passThreshold: string;
  maxDataChars: string;
} {
  const provider = (raw.provider as Provider | undefined) ?? "";
  const modelAll = (raw.model_all as string | undefined) ?? "";
  const models = (raw.models as AgentModels | undefined) ?? {};
  const visualStyle = (raw.visual_style as VisualStyle | undefined) ?? "";
  const maxIterations =
    raw.max_iterations !== undefined && raw.max_iterations !== null
      ? String(raw.max_iterations)
      : "";
  const passThreshold =
    raw.pass_threshold !== undefined && raw.pass_threshold !== null
      ? String(raw.pass_threshold)
      : "";
  const maxDataChars =
    raw.max_data_chars !== undefined && raw.max_data_chars !== null
      ? String(raw.max_data_chars)
      : "";
  return {
    provider: provider || "",
    modelAll,
    agents: {
      analyzer: models.analyzer ?? "",
      planner: models.planner ?? "",
      designer: models.designer ?? "",
      assembler: models.assembler ?? "",
      critic: models.critic ?? "",
    },
    visualStyle: visualStyle || "",
    maxIterations,
    passThreshold,
    maxDataChars,
  };
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const prefsQuery = useQuery({
    queryKey: ["preferences"],
    queryFn: getPreferences,
  });
  const keysQuery = useQuery({
    queryKey: ["keys"],
    queryFn: listKeys,
  });

  const [provider, setProvider] = useState<Provider | "">("");
  const [modelAll, setModelAll] = useState("");
  const [agents, setAgents] = useState<AgentModels>({
    analyzer: "",
    planner: "",
    designer: "",
    assembler: "",
    critic: "",
  });
  const [visualStyle, setVisualStyle] = useState<VisualStyle | "">("");
  const [maxIterations, setMaxIterations] = useState("");
  const [passThreshold, setPassThreshold] = useState("");
  const [maxDataChars, setMaxDataChars] = useState("");

  useEffect(() => {
    if (!prefsQuery.data) return;
    const p = parseSettings(prefsQuery.data.settings);
    setProvider(p.provider);
    setModelAll(p.modelAll);
    setAgents(p.agents);
    setVisualStyle(p.visualStyle);
    setMaxIterations(p.maxIterations);
    setPassThreshold(p.passThreshold);
    setMaxDataChars(p.maxDataChars);
  }, [prefsQuery.data]);

  const savePrefs = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof putPreferences>[0] = {};
      if (provider) body.provider = provider;
      const ma = modelAll.trim();
      if (ma) body.model_all = ma;
      const models: AgentModels = {};
      let has = false;
      (
        ["analyzer", "planner", "designer", "assembler", "critic"] as const
      ).forEach((k) => {
        const v = agents[k]?.trim();
        if (v) {
          models[k] = v;
          has = true;
        }
      });
      if (has) body.models = models;
      if (visualStyle) body.visual_style = visualStyle;
      const mi = parseInt(maxIterations, 10);
      if (!Number.isNaN(mi)) body.max_iterations = mi;
      const pt = parseFloat(passThreshold);
      if (!Number.isNaN(pt)) body.pass_threshold = pt;
      const mdc = parseInt(maxDataChars, 10);
      if (!Number.isNaN(mdc)) body.max_data_chars = mdc;
      return putPreferences(body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
  });

  const [newProvider, setNewProvider] = useState<Provider>("openrouter");
  const [newLabel, setNewLabel] = useState("default");
  const [newKey, setNewKey] = useState("");

  const addKeyMut = useMutation({
    mutationFn: () =>
      createKey({
        provider: newProvider,
        label: newLabel || "default",
        api_key: newKey,
      }),
    onSuccess: () => {
      setNewKey("");
      void queryClient.invalidateQueries({ queryKey: ["keys"] });
    },
  });

  const delKeyMut = useMutation({
    mutationFn: (id: string) => deleteKey(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["keys"] });
    },
  });

  function setAgentField(key: keyof AgentModels, value: string) {
    setAgents((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Settings</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Default pipeline preferences and API keys stored for your account.
        </p>
      </div>

      <section className="rounded-2xl border border-black/5 bg-surface-card p-6 shadow-sm">
        <h2 className="text-lg font-medium text-ink">Default preferences</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Merged into each render unless you override in New report.
        </p>
        {prefsQuery.isLoading && (
          <p className="mt-4 text-sm text-ink-muted">Loading…</p>
        )}
        {prefsQuery.error && (
          <p className="mt-4 text-sm text-red-700">
            {prefsQuery.error instanceof Error
              ? prefsQuery.error.message
              : "Failed to load"}
          </p>
        )}
        {!prefsQuery.isLoading && (
          <div className="mt-6 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-xs font-medium text-ink-muted">
                Provider
                <select
                  value={provider}
                  onChange={(e) =>
                    setProvider(e.target.value as Provider | "")
                  }
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                >
                  <option value="">(none)</option>
                  <option value="openrouter">openrouter</option>
                  <option value="gemini">gemini</option>
                  <option value="nvidia">nvidia</option>
                </select>
              </label>
              <label className="block text-xs font-medium text-ink-muted">
                Model (all agents)
                <input
                  value={modelAll}
                  onChange={(e) => setModelAll(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs font-medium text-ink-muted">
                Visual style
                <select
                  value={visualStyle}
                  onChange={(e) =>
                    setVisualStyle(e.target.value as VisualStyle | "")
                  }
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                >
                  <option value="">(none)</option>
                  <option value="notebooklm">notebooklm</option>
                  <option value="modern">modern</option>
                  <option value="dark">dark</option>
                  <option value="auto">auto</option>
                </select>
              </label>
              <label className="block text-xs font-medium text-ink-muted">
                Max iterations
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={maxIterations}
                  onChange={(e) => setMaxIterations(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs font-medium text-ink-muted">
                Pass threshold
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={10}
                  value={passThreshold}
                  onChange={(e) => setPassThreshold(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs font-medium text-ink-muted">
                Max data chars
                <input
                  type="number"
                  min={1000}
                  value={maxDataChars}
                  onChange={(e) => setMaxDataChars(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                />
              </label>
            </div>
            <div>
              <div className="text-xs font-medium text-ink-muted">
                Per-agent models
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {(
                  [
                    "analyzer",
                    "planner",
                    "designer",
                    "assembler",
                    "critic",
                  ] as const
                ).map((k) => (
                  <input
                    key={k}
                    value={agents[k] ?? ""}
                    onChange={(e) => setAgentField(k, e.target.value)}
                    placeholder={k}
                    className="rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                  />
                ))}
              </div>
            </div>
            {savePrefs.error && (
              <p className="text-sm text-red-700">
                {savePrefs.error instanceof Error
                  ? savePrefs.error.message
                  : "Save failed"}
              </p>
            )}
            <button
              type="button"
              disabled={savePrefs.isPending}
              onClick={() => savePrefs.mutate()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
            >
              {savePrefs.isPending ? "Saving…" : "Save preferences"}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-black/5 bg-surface-card p-6 shadow-sm">
        <h2 className="text-lg font-medium text-ink">LLM API keys</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Keys are encrypted server-side. Reference them by ID in pipeline
          options when needed.
        </p>

        {keysQuery.isLoading && (
          <p className="mt-4 text-sm text-ink-muted">Loading…</p>
        )}
        {keysQuery.data && keysQuery.data.length > 0 && (
          <ul className="mt-4 divide-y divide-black/5 rounded-xl border border-black/5">
            {keysQuery.data.map((k) => (
              <li
                key={k.id}
                className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
              >
                <div>
                  <div className="text-sm font-medium text-ink">
                    {k.label}{" "}
                    <span className="font-normal text-ink-muted">
                      ({k.provider})
                    </span>
                  </div>
                  <div className="font-mono text-xs text-ink-muted">
                    {k.masked_hint}
                  </div>
                  <div className="text-xs text-ink-muted">
                    id: {k.id}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm("Delete this key?")) delKeyMut.mutate(k.id);
                  }}
                  className="rounded-lg border border-red-200 px-3 py-1.5 text-xs text-red-800 hover:bg-red-50"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-6 rounded-xl border border-dashed border-black/15 p-4">
          <div className="text-sm font-medium text-ink">Add key</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <select
              value={newProvider}
              onChange={(e) => setNewProvider(e.target.value as Provider)}
              className="rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
            >
              <option value="openrouter">openrouter</option>
              <option value="gemini">gemini</option>
              <option value="nvidia">nvidia</option>
            </select>
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Label"
              className="rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
            />
            <input
              type="password"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="API key"
              className="rounded-lg border border-black/10 bg-white px-3 py-2 text-sm sm:col-span-3"
            />
          </div>
          {addKeyMut.error && (
            <p className="mt-2 text-sm text-red-700">
              {addKeyMut.error instanceof Error
                ? addKeyMut.error.message
                : "Failed"}
            </p>
          )}
          <button
            type="button"
            disabled={addKeyMut.isPending || !newKey.trim()}
            onClick={() => addKeyMut.mutate()}
            className="mt-3 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-ink/90 disabled:opacity-60"
          >
            {addKeyMut.isPending ? "Adding…" : "Add key"}
          </button>
        </div>
      </section>
    </div>
  );
}
