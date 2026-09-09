import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import TicketList from "./pages/TicketList";
import TicketDetail from "./pages/TicketDetail";
import { api } from "./api";

export default function App() {
  const [phase, setPhase] = useState<number | null>(null);

  useEffect(() => {
    api<{ ok: boolean; phase: number }>("/api/health")
      .then((h) => setPhase(h.phase))
      .catch(() => setPhase(null));
  }, []);

  return (
    <div className="layout">
      <header className="topbar">
        <strong>CodePilot</strong>
        <span className="muted">
          AI Software Engineer{phase ? ` · Phase ${phase}` : ""}
        </span>
      </header>
      <Routes>
        <Route path="/" element={<TicketList />} />
        <Route path="/tickets/:id" element={<TicketDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
