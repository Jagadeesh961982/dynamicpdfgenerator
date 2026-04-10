import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { renderFile, renderJson } from "@/api/client";
import type {
  AgentModels,
  Provider,
  RenderJsonBody,
  VisualStyle,
} from "@/api/types";

type InputMode = "text" | "file" | "json";

const emptyAgentModels = (): AgentModels => ({
  analyzer: "",
  planner: "",
  designer: "",
  assembler: "",
  critic: "",
});

function buildOptions(
  provider: Provider | "",
  modelAll: string,
  agents: AgentModels,
  visualStyle: VisualStyle | "",
  maxIterations: string,
  passThreshold: string,
  designSeed: string,
  htmlOnly: boolean,
  credentialIds: string,
): Record<string, unknown> {
  const o: Record<string, unknown> = {};
  if (provider) o.provider = provider;
  const ma = modelAll.trim();
  if (ma) o.model_all = ma;
  const models: AgentModels = {};
  let hasAgent = false;
  (["analyzer", "planner", "designer", "assembler", "critic"] as const).forEach(
    (k) => {
      const v = agents[k]?.trim();
      if (v) {
        models[k] = v;
        hasAgent = true;
      }
    },
  );
  if (hasAgent) o.models = models;
  if (visualStyle) o.visual_style = visualStyle;
  const mi = parseInt(maxIterations, 10);
  if (!Number.isNaN(mi)) o.max_iterations = mi;
  const pt = parseFloat(passThreshold);
  if (!Number.isNaN(pt)) o.pass_threshold = pt;
  const ds = parseInt(designSeed, 10);
  if (!Number.isNaN(ds)) o.design_seed = ds;
  o.html_only = htmlOnly;
  const ids = credentialIds
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (ids.length) o.credential_ids = ids;
  return o;
}

export function NewReportPage() {
  const queryClient = useQueryClient();
  const [inputMode, setInputMode] = useState<InputMode>("text");
  const [text, setText] = useState("");
  const [jsonText, setJsonText] = useState('{\n  "example": true\n}');
  const [file, setFile] = useState<File | null>(null);

  const [provider, setProvider] = useState<Provider | "">("");
  const [modelAll, setModelAll] = useState("");
  const [agents, setAgents] = useState<AgentModels>(emptyAgentModels);
  const [visualStyle, setVisualStyle] = useState<VisualStyle | "">("notebooklm");
  const [maxIterations, setMaxIterations] = useState("5");
  const [passThreshold, setPassThreshold] = useState("7");
  const [designSeed, setDesignSeed] = useState("");
  const [htmlOnly, setHtmlOnly] = useState(false);
  const [credentialIds, setCredentialIds] = useState("");

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewKind, setPreviewKind] = useState<"pdf" | "html" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const optionsPayload = useMemo(
    () =>
      buildOptions(
        provider,
        modelAll,
        agents,
        visualStyle,
        maxIterations,
        passThreshold,
        designSeed,
        htmlOnly,
        credentialIds,
      ),
    [
      provider,
      modelAll,
      agents,
      visualStyle,
      maxIterations,
      passThreshold,
      designSeed,
      htmlOnly,
      credentialIds,
    ],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const runMutation = useMutation({
    mutationFn: async () => {
      setError(null);
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        setPreviewUrl(null);
        setPreviewKind(null);
      }

      const opts = optionsPayload;

      if (inputMode === "file") {
        if (!file) throw new Error("Choose a file");
        return renderFile({
          file,
          options: opts,
        });
      }

      if (inputMode === "text") {
        const t = text.trim();
        if (!t) throw new Error("Enter text");
        const body = { ...opts, text: t } as RenderJsonBody;
        return renderJson(body);
      }

      let structured: Record<string, unknown>;
      try {
        structured = JSON.parse(jsonText) as Record<string, unknown>;
        if (structured === null || typeof structured !== "object")
          throw new Error("JSON must be an object");
      } catch {
        throw new Error("Invalid JSON object");
      }
      const body = { ...opts, structured } as RenderJsonBody;
      return renderJson(body);
    },
    onSuccess: (result) => {
      const { blob, contentType } = result;
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
      if (
        contentType?.includes("pdf") ||
        blob.type === "application/pdf"
      ) {
        setPreviewKind("pdf");
      } else {
        setPreviewKind("html");
      }
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  function setAgentField(key: keyof AgentModels, value: string) {
    setAgents((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 lg:flex-row">
      <div className="min-w-0 flex-1 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-ink">New report</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Provide a source, tune pipeline options, then generate PDF or HTML.
          </p>
        </div>

        <div className="rounded-2xl border border-black/5 bg-surface-card p-5 shadow-sm">
          <div className="text-sm font-medium text-ink">Source</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(
              [
                ["text", "Paste text"],
                ["file", "Upload file"],
                ["json", "Structured JSON"],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setInputMode(mode)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                  inputMode === mode
                    ? "bg-ink text-white"
                    : "bg-black/5 text-ink-muted hover:bg-black/10"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {inputMode === "text" && (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste document text…"
              rows={12}
              className="mt-4 w-full rounded-xl border border-black/10 bg-white p-3 font-mono text-sm outline-none ring-accent/30 focus:ring-2"
            />
          )}
          {inputMode === "file" && (
            <div className="mt-4">
              <input
                type="file"
                accept=".pdf,.csv,.txt,.json,.md"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              <p className="mt-2 text-xs text-ink-muted">
                PDF, CSV, TXT, JSON, or Markdown.
              </p>
            </div>
          )}
          {inputMode === "json" && (
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              rows={12}
              className="mt-4 w-full rounded-xl border border-black/10 bg-white p-3 font-mono text-sm outline-none ring-accent/30 focus:ring-2"
            />
          )}
        </div>

        <div className="rounded-2xl border border-black/5 bg-surface-card p-5 shadow-sm">
          <div className="text-sm font-medium text-ink">Pipeline options</div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-ink-muted">
              Provider
              <select
                value={provider}
                onChange={(e) =>
                  setProvider(e.target.value as Provider | "")
                }
                className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm text-ink"
              >
                <option value="">(default)</option>
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
                placeholder="e.g. model id"
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
              Design seed (optional)
              <input
                type="number"
                value={designSeed}
                onChange={(e) => setDesignSeed(e.target.value)}
                className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-4">
            <div className="text-xs font-medium text-ink-muted">
              Per-agent models (optional)
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
          <label className="mt-4 flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={htmlOnly}
              onChange={(e) => setHtmlOnly(e.target.checked)}
            />
            HTML only (skip PDF)
          </label>
          <label className="mt-3 block text-xs font-medium text-ink-muted">
            Credential IDs (comma-separated)
            <input
              value={credentialIds}
              onChange={(e) => setCredentialIds(e.target.value)}
              placeholder="uuid …"
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 font-mono text-sm"
            />
          </label>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        <button
          type="button"
          disabled={runMutation.isPending}
          onClick={() => runMutation.mutate()}
          className="rounded-xl bg-accent px-6 py-3 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-60"
        >
          {runMutation.isPending ? "Generating…" : "Generate"}
        </button>
      </div>

      <div className="w-full shrink-0 lg:w-[44%]">
        <div className="sticky top-6 rounded-2xl border border-black/5 bg-surface-card p-4 shadow-sm">
          <div className="text-sm font-medium text-ink">Preview</div>
          <p className="mt-1 text-xs text-ink-muted">
            Output appears here when generation completes.
          </p>
          <div className="mt-4 min-h-[480px] overflow-hidden rounded-xl border border-black/10 bg-white">
            {previewUrl && previewKind === "pdf" && (
              <iframe
                title="PDF preview"
                src={previewUrl}
                className="h-[min(70vh,720px)] w-full"
              />
            )}
            {previewUrl && previewKind === "html" && (
              <iframe
                title="HTML preview"
                src={previewUrl}
                className="h-[min(70vh,720px)] w-full"
                sandbox="allow-scripts allow-same-origin"
              />
            )}
            {!previewUrl && (
              <div className="flex h-[min(70vh,720px)] items-center justify-center text-sm text-ink-muted">
                No preview yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
