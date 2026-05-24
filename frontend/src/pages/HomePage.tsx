import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Download, Trash2, FilePlus, RefreshCw, CheckCircle2,
  XCircle, Clock, Activity, TrendingUp, FileText, Loader2, AlertCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import { deleteJob, downloadJob, getAdminStats, listJobs } from "@/api/client";
import type { JobOut } from "@/api/types";
import { useAuth } from "@/context/AuthContext";

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

function StatusBadge({ status }: { status: string }) {
  if (status === "done")    return <span className="badge-ok"><CheckCircle2 className="w-3 h-3" />Done</span>;
  if (status === "failed")  return <span className="badge-err"><XCircle className="w-3 h-3" />Failed</span>;
  if (status === "running") return <span className="badge-warn"><Loader2 className="w-3 h-3 animate-spin" />Running</span>;
  return <span className="badge-info"><Clock className="w-3 h-3" />{status}</span>;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function HomePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: stats } = useQuery({ queryKey: ["admin-stats"], queryFn: getAdminStats });
  const { data: jobs = [], isLoading, refetch } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => listJobs(100),
    refetchInterval: (q) => {
      const hasRunning = (q.state.data as JobOut[] | undefined)?.some((j) => j.status === "running");
      return hasRunning ? 5000 : false;
    },
  });

  const dlMut = useMutation({
    mutationFn: (jobId: string) => downloadJob(jobId),
    onSuccess: ({ blob, contentType, filename }) => {
      const ext = contentType?.includes("pdf") ? ".pdf" : ".html";
      saveBlob(blob, filename ?? `report${ext}`);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Download failed"),
  });

  const delMut = useMutation({
    mutationFn: (jobId: string) => deleteJob(jobId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); qc.invalidateQueries({ queryKey: ["admin-stats"] }); toast.success("Job deleted"); },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const STAT_CARDS = [
    { label: "Total Reports",  value: stats?.total_jobs ?? 0, icon: FileText,  color: "text-info",  bg: "bg-info-soft" },
    { label: "Completed",      value: stats?.done ?? 0,       icon: CheckCircle2, color: "text-ok",  bg: "bg-ok-soft" },
    { label: "Failed",         value: stats?.failed ?? 0,     icon: XCircle,   color: "text-err",   bg: "bg-err-soft" },
    { label: "Running",        value: stats?.running ?? 0,    icon: Activity,  color: "text-warn",  bg: "bg-warn-soft" },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <p className="text-txt-muted text-sm">{greeting},</p>
          <h1 className="text-2xl font-bold text-txt-primary">{user?.email?.split("@")[0]}</h1>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="btn-ghost gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
          <button onClick={() => navigate("/report")} className="btn-primary">
            <FilePlus className="w-4 h-4" />
            New Report
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {STAT_CARDS.map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="card p-5">
            <div className={`w-9 h-9 rounded-xl ${bg} flex items-center justify-center mb-3`}>
              <Icon className={`w-4.5 h-4.5 ${color}`} />
            </div>
            <p className="text-2xl font-bold text-txt-primary">{value}</p>
            <p className="text-xs text-txt-muted mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Jobs table */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-txt-muted" />
            <h2 className="text-sm font-semibold text-txt-primary">Recent Reports</h2>
          </div>
          <span className="text-xs text-txt-subtle">{jobs.length} total</span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-5 h-5 animate-spin text-brand" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-14 h-14 rounded-2xl bg-brand-soft flex items-center justify-center mb-4">
              <FileText className="w-7 h-7 text-brand-light" />
            </div>
            <p className="text-txt-primary font-medium">No reports yet</p>
            <p className="text-txt-subtle text-sm mt-1 mb-5">Generate your first AI-powered PDF report</p>
            <button onClick={() => navigate("/report")} className="btn-primary">
              <FilePlus className="w-4 h-4" /> Create Report
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center gap-4 px-5 py-3.5 hover:bg-bg-hover/50 transition-colors group">
                <div className="w-8 h-8 rounded-lg bg-bg-elevated flex items-center justify-center flex-shrink-0">
                  <FileText className="w-3.5 h-3.5 text-txt-muted" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-txt-primary truncate font-medium">
                    {job.input_filename ?? `report_${job.id.slice(0, 8)}`}
                  </p>
                  <p className="text-xs text-txt-subtle mt-0.5">
                    {fmtDate(job.created_at)}
                    {job.completed_at && ` · ${fmtDate(job.completed_at)}`}
                  </p>
                </div>
                <StatusBadge status={job.status} />
                {job.error_message && (
                  <div title={job.error_message} className="text-err">
                    <AlertCircle className="w-4 h-4" />
                  </div>
                )}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {job.status === "done" && (
                    <button
                      onClick={() => dlMut.mutate(job.id)}
                      disabled={dlMut.isPending}
                      className="btn-ghost px-2 py-1.5"
                      title="Download"
                    >
                      <Download className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {job.status !== "running" && (
                    <button
                      onClick={() => { if (confirm("Delete this job?")) delMut.mutate(job.id); }}
                      className="btn-danger px-2 py-1.5"
                      title="Delete"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
