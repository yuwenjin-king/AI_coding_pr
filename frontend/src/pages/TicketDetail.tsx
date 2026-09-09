import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AgentRun, type TicketDetail as TicketDetailType } from "../api";

const ACTIVE_STATUSES = ["queued", "running"];

type TraceEvent = {
  step?: number;
  type: string;
  content?: string | null;
  name?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  blocked?: boolean;
  output?: string;
  tool_calls?: Array<{ id: string; name: string; arguments: string }>;
};

function fmtArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  const parts = Object.entries(args)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  return parts.join(" ");
}

function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

export default function TicketDetail() {
  const { id } = useParams();
  const [ticket, setTicket] = useState<TicketDetailType | null>(null);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sseFailed, setSseFailed] = useState(false);

  const load = useCallback(async () => {
    const data = await api<TicketDetailType>(`/api/tickets/${id}`);
    setTicket(data);
    const latest = data.runs?.length
      ? [...data.runs].sort((a, b) => b.id - a.id)[0]
      : null;
    setRun(latest);
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [load]);

  const active = !!run && ACTIVE_STATUSES.includes(run.status);

  // Live updates over SSE; fall back to polling when EventSource fails.
  useEffect(() => {
    if (!run || !ACTIVE_STATUSES.includes(run.status)) return;
    if (sseFailed) return;
    const es = new EventSource(`/api/runs/${run.id}/events`);
    es.onmessage = (e) => {
      try {
        setRun(JSON.parse(e.data) as AgentRun);
      } catch {
        /* ignore malformed snapshot */
      }
    };
    es.addEventListener("done", () => es.close());
    es.onerror = () => {
      es.close();
      setSseFailed(true);
    };
    return () => es.close();
  }, [run?.id, active, sseFailed]);

  useEffect(() => {
    if (!run || !ACTIVE_STATUSES.includes(run.status) || !sseFailed) return;
    const timer = window.setInterval(async () => {
      const next = await api<AgentRun>(`/api/runs/${run.id}`);
      setRun(next);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run?.id, active, sseFailed]);

  const start = async () => {
    setBusy(true);
    setError(null);
    setSseFailed(false);
    try {
      const created = await api<AgentRun>(`/api/tickets/${id}/runs`, { method: "POST" });
      setRun(created);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const hitl = async (decision: "approve" | "reject") => {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api<AgentRun>(`/api/runs/${run.id}/hitl`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setRun(updated);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const plan = useMemo(() => {
    if (!run?.plan_json) return [];
    try {
      return JSON.parse(run.plan_json) as string[];
    } catch {
      return [];
    }
  }, [run?.plan_json]);

  const trace = useMemo(() => {
    if (!run?.trace_json) return [];
    try {
      return JSON.parse(run.trace_json) as TraceEvent[];
    } catch {
      return [];
    }
  }, [run?.trace_json]);

  const suggestedFiles = useMemo(() => {
    const text = run?.report_md || "";
    const matches = text.match(/[\w./-]+\.py/g) || [];
    return Array.from(new Set(matches)).slice(0, 8);
  }, [run?.report_md]);

  if (!ticket) {
    return (
      <main className="page">
        {error ? <p className="error">{error}</p> : <p>加载中…</p>}
      </main>
    );
  }

  return (
    <main className="page">
      <Link to="/">← 工单列表</Link>
      <header className="detail-head">
        <h1>
          <span className={`badge ${ticket.type}`}>{ticket.code}</span> {ticket.title}
        </h1>
        <button disabled={busy || active} onClick={start}>
          {active ? "AI 处理中…" : "让 AI 处理"}
        </button>
      </header>
      <pre className="desc">{ticket.description}</pre>
      {error && <p className="error">{error}</p>}

      {run && (
        <section className="panel">
          <h2>
            AI Analysis · Run #{run.id}{" "}
            <span className={`status status-${run.status}`}>{run.status}</span>
            {active && <span className="live-dot" title="实时事件流已连接" />}
          </h2>
          {plan.length > 0 && (
            <>
              <h3>Plan</h3>
              <ol>
                {plan.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ol>
            </>
          )}
          {run.error && <p className="error">{run.error}</p>}
          {run.report_md && (
            <>
              <h3>Root Cause / 方案</h3>
              <pre className="report">{run.report_md}</pre>
            </>
          )}
          {run.mode === "coding" && run.branch && (
            <p className="muted">
              分支 <code>{run.branch}</code>
              {run.workspace ? " · 隔离工作区待审批" : " · 工作区已清理"}
            </p>
          )}
          {run.test_summary && (
            <>
              <h3>Tests</h3>
              <pre className="observation">{run.test_summary}</pre>
            </>
          )}
          {run.diff_md && (
            <>
              <h3>代码 Diff</h3>
              <pre className="diff-view">{run.diff_md}</pre>
            </>
          )}
          <h3>Modified Files</h3>
          {suggestedFiles.length ? (
            <ul>
              {suggestedFiles.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">分析模式不改代码，仅建议路径（从报告中提取）。</p>
          )}
          <h3>运行日志（思考 → 行动 → 观察）</h3>
          <ol className="trace">
            {trace.map((ev, i) => (
              <li key={i} className={`trace-item ${ev.type}`}>
                {ev.type === "llm" ? (
                  <>
                    <span className="tag tag-llm">LLM</span>
                    <span className="muted"> step {String(ev.step)} · </span>
                    {ev.content ? <span className="thought">{truncate(ev.content, 120)}</span> : <span className="muted">（无文本，直接调工具）</span>}
                    {(ev.tool_calls || []).map((tc) => (
                      <span key={tc.id} className="chip">
                        {tc.name}({truncate(fmtArgs(safeParse(tc.arguments)), 60)})
                      </span>
                    ))}
                  </>
                ) : ev.type === "tool" ? (
                  <details>
                    <summary>
                      <span className={`tag ${ev.blocked ? "tag-blocked" : ev.ok ? "tag-ok" : "tag-fail"}`}>
                        {ev.blocked ? "BLOCKED" : ev.ok ? "OK" : "FAIL"}
                      </span>{" "}
                      <code>{String(ev.name)}</code>{" "}
                      <span className="muted">{truncate(fmtArgs(ev.arguments), 80)}</span>
                    </summary>
                    <pre className="observation">{ev.output || "(empty)"}</pre>
                  </details>
                ) : (
                  <span className="muted">{JSON.stringify(ev).slice(0, 120)}</span>
                )}
              </li>
            ))}
            {active && <li className="trace-item pending">等待下一步…</li>}
          </ol>
          {run.status === "needs_review" ? (
            <div className="review-box">
              <p>
                <strong>等待人工审批</strong> —— 批准将合并 <code>{run.branch}</code> 到主分支；拒绝将丢弃工作区。
              </p>
              <div className="actions">
                <button className="approve" disabled={busy} onClick={() => hitl("approve")}>
                  批准并合并
                </button>
                <button className="reject" disabled={busy} onClick={() => hitl("reject")}>
                  拒绝并丢弃
                </button>
              </div>
            </div>
          ) : (
            <div className="actions">
              <button disabled title={run.diff_md ? "Diff 见上方" : "Phase 4 可用"}>
                查看代码 Diff
              </button>
              <button disabled title="needs_review 状态时可用">
                批准
              </button>
              <button disabled title="needs_review 状态时可用">
                拒绝
              </button>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function safeParse(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw || "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
}
