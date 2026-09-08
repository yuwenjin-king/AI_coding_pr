import { Navigate, Route, Routes } from "react-router-dom";
import TicketList from "./pages/TicketList";
import TicketDetail from "./pages/TicketDetail";

export default function App() {
  return (
    <div className="layout">
      <header className="topbar">
        <strong>CodePilot</strong>
        <span className="muted">AI Software Engineer · Phase 2 · Tool Agent</span>
      </header>
      <Routes>
        <Route path="/" element={<TicketList />} />
        <Route path="/tickets/:id" element={<TicketDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
