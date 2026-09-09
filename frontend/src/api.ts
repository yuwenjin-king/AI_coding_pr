export type Ticket = {
  id: number;
  project_id: number;
  code: string;
  type: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
};

export type AgentRun = {
  id: number;
  ticket_id: number;
  status: string;
  mode: string;
  plan_json: string | null;
  report_md: string | null;
  trace_json: string | null;
  branch: string | null;
  workspace: string | null;
  diff_md: string | null;
  test_summary: string | null;
  error: string | null;
  created_at: string;
  updated_at: string | null;
};

export type TicketDetail = Ticket & { runs: AgentRun[] };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}
