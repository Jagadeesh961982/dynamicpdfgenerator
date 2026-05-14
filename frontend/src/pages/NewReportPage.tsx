import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  Upload, Type, Code, Zap, Download, Settings2, ChevronDown,
  ChevronUp, X, FileText, Loader2, CheckCircle2, Sparkles, Globe, Presentation,
} from "lucide-react";
import toast from "react-hot-toast";
import { renderFile, renderJson } from "@/api/client";
import type { Provider, VisualStyle } from "@/api/types";

type InputMode = "text" | "file" | "json";

const PIPELINE_STAGES_BASE = [
  { label: "Analyzing content",        pct: 15 },
  { label: "Planning narrative",        pct: 30 },
  { label: "Designing slides",          pct: 65 },
  { label: "Assembling document",       pct: 85 },
  { label: "Running quality checks",    pct: 95 },
  { label: "Exporting",                 pct: 100 },
];

const PIPELINE_STAGES_BROWSER = [
  { label: "Web research",              pct: 12 },
  { label: "Analyzing content",        pct: 25 },
  { label: "Planning narrative",        pct: 38 },
  { label: "Designing slides",          pct: 70 },
  { label: "Assembling document",       pct: 87 },
  { label: "Running quality checks",    pct: 96 },
  { label: "Exporting",                 pct: 100 },
];

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

export function NewReportPage() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode]         = useState<InputMode>("text");
  const [text, setText]         = useState("");
  const [jsonText, setJsonText] = useState("{}");
  const [file, setFile]         = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [showOpts, setShowOpts] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState<"pdf" | "pptx" | "html" | null>(null);
  const [stageIdx, setStageIdx] = useState(0);

  // Options state
  const [provider, setProvider]     = useState<Provider>("openrouter");
  const [modelAll, setModelAll]     = useState("google/gemini-3.1-flash-lite-preview");
  const [style, setStyle]           = useState<VisualStyle>("auto");
  const [iterations, setIterations] = useState(3);
  const [threshold, setThreshold]   = useState(7.5);
  const [htmlOnly, setHtmlOnly]     = useState(false);
  const [browserEnabled, setBrowserEnabled] = useState(false);
  const [browserMaxPages, setBrowserMaxPages] = useState(5);
  const [outputFormat, setOutputFormat] = useState<"pdf" | "pptx">("pdf");

  const mut = useMutation({
    mutationFn: async () => {
      // Advance stages while waiting
      setStageIdx(0);
      let idx = 0;
      const timer = setInterval(() => {
        if (idx < PIPELINE_STAGES.length - 1) {
          idx++;
          setStageIdx(idx);
        }
      }, 12000);

      const opts = {
        provider, model_all: modelAll || undefined,
        visual_style: style, max_iterations: iterations,
        pass_threshold: threshold, html_only: htmlOnly,
        output_format: outputFormat,
        ...(browserEnabled && {
          browser_enabled: true,
          browser_max_pages: browserMaxPages,
        }),
      };
      try {
        if (mode === "file" && file) {
          return await renderFile({ file, options: opts });
        } else if (mode === "json") {
          let parsed: Record<string, unknown>;
          try { parsed = JSON.parse(jsonText); } catch { throw new Error("Invalid JSON"); }
          return await renderJson({ structured: parsed, ...opts });
        } else {
          return await renderJson({ text, ...opts });
        }
      } finally {
        clearInterval(timer);
        setStageIdx(PIPELINE_STAGES.length - 1);
      }
    },
    onSuccess: ({ blob, contentType, filename }) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["admin-stats"] });
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
      setPreviewType(
        contentType?.includes("presentationml") ? "pptx"
        : contentType?.includes("pdf") ? "pdf"
        : "html"
      );
      toast.success("Report generated successfully!");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Generation failed"),
  });

  const exportLabel = htmlOnly ? "Exporting HTML" : outputFormat === "pptx" ? "Exporting PPTX" : "Exporting PDF";
  const _stagesBase = browserEnabled ? PIPELINE_STAGES_BROWSER : PIPELINE_STAGES_BASE;
  const PIPELINE_STAGES = _stagesBase.map((s, i, arr) =>
    i === arr.length - 1 ? { ...s, label: exportLabel } : s
  );
  const currentStage = PIPELINE_STAGES[stageIdx];
  const progress = mut.isPending ? currentStage.pct : (mut.isSuccess ? 100 : 0);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) { setFile(f); setMode("file"); }
  }

  const canGenerate = mode === "text" ? text.trim().length > 0
    : mode === "file" ? !!file
    : jsonText.trim() !== "";

  return (
    <div className="p-6 max-w-5xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-7 h-7 rounded-lg bg-brand-soft flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-brand-light" />
          </div>
          <h1 className="text-xl font-bold text-txt-primary">New Report</h1>
        </div>
        <p className="text-sm text-txt-muted ml-9">Generate an executive PDF from your data</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* Input panel */}
        <div className="lg:col-span-3 space-y-4">
          {/* Mode tabs */}
          <div className="card p-1 flex gap-1">
            {([
              { id: "text", icon: Type,     label: "Paste Text" },
              { id: "file", icon: Upload,   label: "Upload File" },
              { id: "json", icon: Code,     label: "JSON Data" },
            ] as const).map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                onClick={() => setMode(id)}
                className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-all duration-150
                  ${mode === id ? "bg-brand text-white" : "text-txt-muted hover:text-txt-primary hover:bg-bg-hover"}`}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </button>
            ))}
          </div>

          {/* Text input */}
          {mode === "text" && (
            <div className="card overflow-hidden">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste your data, logs, alerts, or any text content here…&#10;&#10;Supports infrastructure logs, metrics, CSV data, markdown, or plain text."
                className="w-full h-64 bg-transparent p-4 text-sm text-txt-primary placeholder:text-txt-subtle resize-none outline-none font-mono"
              />
              <div className="flex justify-between items-center px-4 py-2 border-t border-border bg-bg-elevated/30">
                <span className="text-xs text-txt-subtle">{text.length.toLocaleString()} chars</span>
                {text && (
                  <button onClick={() => setText("")} className="text-xs text-txt-subtle hover:text-err flex items-center gap-1">
                    <X className="w-3 h-3" /> Clear
                  </button>
                )}
              </div>
            </div>
          )}

          {/* File upload */}
          {mode === "file" && (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileRef.current?.click()}
              className={`card p-10 flex flex-col items-center justify-center cursor-pointer text-center transition-all duration-150
                ${dragging ? "border-brand bg-brand-soft" : "hover:border-border-strong hover:bg-bg-elevated"}`}
            >
              <input
                ref={fileRef} type="file"
                accept=".txt,.csv,.pdf,.json,.md"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }}
              />
              {file ? (
                <>
                  <div className="w-12 h-12 rounded-xl bg-ok-soft flex items-center justify-center mb-3">
                    <FileText className="w-6 h-6 text-ok" />
                  </div>
                  <p className="text-sm font-medium text-txt-primary">{file.name}</p>
                  <p className="text-xs text-txt-subtle mt-1">{(file.size / 1024).toFixed(1)} KB · Click to change</p>
                </>
              ) : (
                <>
                  <div className="w-12 h-12 rounded-xl bg-brand-soft flex items-center justify-center mb-3">
                    <Upload className="w-6 h-6 text-brand-light" />
                  </div>
                  <p className="text-sm font-medium text-txt-primary">Drop file here or click to browse</p>
                  <p className="text-xs text-txt-subtle mt-1">Supports .txt, .csv, .pdf, .json, .md</p>
                </>
              )}
            </div>
          )}

          {/* JSON input */}
          {mode === "json" && (
            <div className="card overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-bg-elevated/30">
                <Code className="w-3.5 h-3.5 text-txt-subtle" />
                <span className="text-xs text-txt-muted font-mono">JSON</span>
              </div>
              <textarea
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                className="w-full h-60 bg-transparent p-4 text-sm text-txt-primary font-mono resize-none outline-none"
                spellCheck={false}
              />
            </div>
          )}

          {/* Options accordion */}
          <div className="card overflow-hidden">
            <button
              onClick={() => setShowOpts(!showOpts)}
              className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-txt-muted hover:text-txt-primary transition-colors"
            >
              <span className="flex items-center gap-2">
                <Settings2 className="w-4 h-4" />
                Pipeline Options
              </span>
              {showOpts ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {showOpts && (
              <div className="px-4 pb-4 pt-1 grid grid-cols-2 gap-4 border-t border-border">
                <div>
                  <label className="label">Provider</label>
                  <select value={provider} onChange={(e) => setProvider(e.target.value as Provider)} className="select">
                    <option value="openrouter">OpenRouter</option>
                    <option value="gemini">Gemini</option>
                    <option value="nvidia">NVIDIA</option>
                  </select>
                </div>
                <div>
                  <label className="label">Model</label>
                  <input value={modelAll} onChange={(e) => setModelAll(e.target.value)} className="input" placeholder="google/gemini-3.1-flash-lite-preview" />
                </div>
                <div>
                  <label className="label">Visual Style</label>
                  <select value={style} onChange={(e) => setStyle(e.target.value as VisualStyle)} className="select">
                    <option value="auto">Auto (AI picks)</option>
                    <option value="notebooklm">NotebookLM</option>
                    <option value="modern">Modern</option>
                    <option value="dark">Dark</option>
                  </select>
                </div>
                <div>
                  <label className="label">Max Iterations</label>
                  <input type="number" min={1} max={5} value={iterations} onChange={(e) => setIterations(+e.target.value)} className="input" />
                </div>
                <div>
                  <label className="label">Pass Threshold (0–10)</label>
                  <input type="number" min={0} max={10} step={0.5} value={threshold} onChange={(e) => setThreshold(+e.target.value)} className="input" />
                </div>
                <div className="flex items-center gap-3 pt-5">
                  <input id="html-only" type="checkbox" checked={htmlOnly} onChange={(e) => setHtmlOnly(e.target.checked)}
                    className="w-4 h-4 rounded accent-brand-light" />
                  <label htmlFor="html-only" className="text-sm text-txt-muted cursor-pointer">HTML only (skip export)</label>
                </div>

                {/* Output format selector */}
                <div className="col-span-2">
                  <label className="label mb-1.5">Output Format</label>
                  <div className="flex gap-2">
                    {(["pdf", "pptx"] as const).map((fmt) => (
                      <button
                        key={fmt}
                        type="button"
                        disabled={htmlOnly}
                        onClick={() => setOutputFormat(fmt)}
                        className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed ${
                          outputFormat === fmt && !htmlOnly
                            ? "border-brand-light bg-brand-soft text-brand-light"
                            : "border-border text-txt-muted hover:border-border-strong hover:text-txt-primary"
                        }`}
                      >
                        {fmt === "pdf"
                          ? <FileText className="w-3.5 h-3.5" />
                          : <Presentation className="w-3.5 h-3.5" />}
                        {fmt === "pdf" ? "PDF" : "PowerPoint"}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Browser agent toggle — spans full width */}
                <div className="col-span-2 rounded-xl border border-border bg-bg-elevated/40 p-3 space-y-2">
                  <div className="flex items-center gap-3">
                    <input
                      id="browser-enabled"
                      type="checkbox"
                      checked={browserEnabled}
                      onChange={(e) => setBrowserEnabled(e.target.checked)}
                      className="w-4 h-4 rounded accent-brand-light flex-shrink-0"
                    />
                    <label htmlFor="browser-enabled" className="flex items-center gap-2 text-sm text-txt-muted cursor-pointer">
                      <Globe className="w-3.5 h-3.5 text-brand-light" />
                      Web Research Agent
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-brand-soft text-brand-light font-mono">Beta</span>
                    </label>
                  </div>
                  {browserEnabled && (
                    <div className="pl-7 animate-fade-in">
                      <p className="text-[11px] text-txt-subtle leading-relaxed mb-2">
                        Searches the web for facts, statistics, and recent data before generating slides.
                        Best for short topic inputs (not raw data files).
                      </p>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-txt-subtle">Max pages:</label>
                        <input
                          type="number" min={1} max={20} value={browserMaxPages}
                          onChange={(e) => setBrowserMaxPages(+e.target.value)}
                          className="input w-16 text-xs py-1"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Generate button */}
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !canGenerate}
            className="btn-primary w-full justify-center py-3 text-base"
          >
            {mut.isPending ? (
              <><Loader2 className="w-5 h-5 animate-spin" /> Generating…</>
            ) : (
              <><Zap className="w-5 h-5" /> Generate Report</>
            )}
          </button>

          {/* Progress */}
          {mut.isPending && (
            <div className="card p-4 animate-fade-in">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs font-medium text-txt-muted">{currentStage.label}…</span>
                <span className="text-xs text-brand-light font-mono">{progress}%</span>
              </div>
              <div className="h-1.5 bg-bg-elevated rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-violet-500 to-indigo-600 rounded-full transition-all duration-[3s] ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="flex gap-2 mt-3 flex-wrap">
                {PIPELINE_STAGES.map((s, i) => (
                  <span key={s.label}
                    className={`text-[10px] px-2 py-0.5 rounded-full ${i <= stageIdx ? "bg-brand-soft text-brand-light" : "bg-bg-elevated text-txt-subtle"}`}
                  >
                    {i < stageIdx ? "✓ " : ""}{s.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Preview panel */}
        <div className="lg:col-span-2">
          <div className="card h-full min-h-[500px] flex flex-col overflow-hidden sticky top-6">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <span className="text-sm font-medium text-txt-muted">Preview</span>
              {previewUrl && (
                <button
                  onClick={() => {
                    const ext = previewType === "pdf" ? ".pdf" : previewType === "pptx" ? ".pptx" : ".html";
                    const a = document.createElement("a");
                    a.href = previewUrl; a.download = `report${ext}`;
                    a.click();
                  }}
                  className="btn-primary px-3 py-1.5 text-xs"
                >
                  <Download className="w-3.5 h-3.5" />
                  {previewType === "pptx" ? "Download PPTX" : "Download"}
                </button>
              )}
            </div>

            <div className="flex-1 flex items-center justify-center bg-bg-elevated/30 relative">
              {previewUrl && previewType === "pptx" ? (
                <div className="text-center px-8">
                  <div className="w-16 h-16 rounded-2xl bg-ok-soft flex items-center justify-center mx-auto mb-4">
                    <Presentation className="w-8 h-8 text-ok" />
                  </div>
                  <p className="text-txt-primary text-sm font-medium">PowerPoint ready!</p>
                  <p className="text-txt-subtle text-xs mt-1 leading-relaxed">
                    Click Download PPTX to save your presentation.
                  </p>
                </div>
              ) : previewUrl ? (
                <iframe
                  src={previewUrl}
                  className="w-full h-full border-0"
                  title="Report Preview"
                  sandbox={previewType === "html" ? "allow-scripts allow-same-origin" : undefined}
                />
              ) : mut.isPending ? (
                <div className="text-center">
                  <div className="w-16 h-16 rounded-2xl bg-brand-soft flex items-center justify-center mx-auto mb-4">
                    <Loader2 className="w-8 h-8 text-brand-light animate-spin" />
                  </div>
                  <p className="text-txt-muted text-sm font-medium">Generating report…</p>
                  <p className="text-txt-subtle text-xs mt-1">This usually takes 2–5 minutes</p>
                </div>
              ) : mut.isSuccess ? (
                <div className="text-center">
                  <CheckCircle2 className="w-10 h-10 text-ok mx-auto mb-3" />
                  <p className="text-txt-primary text-sm font-medium">Report ready!</p>
                </div>
              ) : (
                <div className="text-center px-8">
                  <div className="w-16 h-16 rounded-2xl bg-bg-elevated flex items-center justify-center mx-auto mb-4">
                    <FileText className="w-8 h-8 text-txt-subtle" />
                  </div>
                  <p className="text-txt-muted text-sm font-medium">Preview appears here</p>
                  <p className="text-txt-subtle text-xs mt-1 leading-relaxed">
                    Generate a report to see the PDF preview
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
