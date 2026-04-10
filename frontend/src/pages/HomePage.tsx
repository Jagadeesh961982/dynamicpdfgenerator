import { useQuery } from "@tanstack/react-query";

import { downloadJob, listJobs } from "@/api/client";
import type { JobOut } from "@/api/types";

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    done: "bg-emerald-50 text-emerald-800",
    running: "bg-amber-50 text-amber-800",
    failed: "bg-red-50 text-red-800",
  };
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-800"}`}
    >
      {status}
    </span>
  );
}

export function HomePage() {
  const { data: jobs, isLoading, error, refetch } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => listJobs(50),
  });

  async function handleDownload(job: JobOut) {
    if (job.status !== "done") return;
    try {
      const { blob, filename } = await downloadJob(job.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "download";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Download failed");
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-2xl font-semibold text-ink">Recent activity</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Pipeline jobs and generated reports.
      </p>

      <div className="mt-6 rounded-2xl border border-black/5 bg-surface-card shadow-sm">
        <div className="flex items-center justify-between border-b border-black/5 px-4 py-3">
          <span className="text-sm font-medium text-ink">Jobs</span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="text-sm text-accent hover:underline"
          >
            Refresh
          </button>
        </div>
        {isLoading && (
          <div className="p-8 text-center text-sm text-ink-muted">Loading…</div>
        )}
        {error && (
          <div className="p-8 text-center text-sm text-red-700">
            {error instanceof Error ? error.message : "Failed to load jobs"}
          </div>
        )}
        {!isLoading && !error && jobs && jobs.length === 0 && (
          <div className="p-8 text-center text-sm text-ink-muted">
            No jobs yet. Create a report from{" "}
            <span className="font-medium text-ink">New report</span>.
          </div>
        )}
        {!isLoading && jobs && jobs.length > 0 && (
          <ul className="divide-y divide-black/5">
            {jobs.map((job) => (
              <li
                key={job.id}
                className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-ink">
                    {job.input_filename ?? job.id}
                  </div>
                  <div className="mt-0.5 text-xs text-ink-muted">
                    {new Date(job.created_at).toLocaleString()}
                    {job.completed_at &&
                      ` · done ${new Date(job.completed_at).toLocaleString()}`}
                  </div>
                  {job.error_message && (
                    <div className="mt-1 line-clamp-2 text-xs text-red-700">
                      {job.error_message}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {statusBadge(job.status)}
                  {job.status === "done" && (
                    <button
                      type="button"
                      onClick={() => void handleDownload(job)}
                      className="rounded-lg border border-black/10 bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-black/[0.02]"
                    >
                      Download
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
