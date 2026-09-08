import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Ticket } from "../api";

export default function TicketList() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Ticket[]>("/api/tickets")
      .then(setTickets)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  return (
    <main className="page">
      <h1>工单列表</h1>
      {error && <p className="error">{error}</p>}
      <ul className="ticket-list">
        {tickets.map((t) => (
          <li key={t.id}>
            <Link to={`/tickets/${t.id}`}>
              <span className={`badge ${t.type}`}>{t.code}</span>
              <span>{t.title}</span>
              <span className="muted">{t.status}</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
