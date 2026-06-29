import { useState } from "react";
import { deleteAgent, type Agent } from "../api";

type Props = { agent: Agent; onClose: () => void; onDeleted: (id: number) => void };

export function ConfirmDeleteModal({ agent, onClose, onDeleted }: Props) {
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const matches = confirmText === agent.name;

  async function confirm() {
    if (!matches || deleting) return;
    setDeleting(true);
    setError("");
    try {
      await deleteAgent(agent.id);
      onDeleted(agent.id);
    } catch {
      setError("eliminazione fallita");
      setDeleting(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>Elimina «{agent.name}»</h2>
        <p>Questa azione è irreversibile. Verranno cancellati definitivamente posizioni,
          operazioni, equity, eventi e memoria di questo agente.</p>
        <label htmlFor="confirm-name">Scrivi <b>{agent.name}</b> per confermare</label>
        <input id="confirm-name" value={confirmText} autoFocus
          onChange={(e) => setConfirmText(e.target.value)} />
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Annulla</button>
          <button type="button" className="btn-danger" disabled={!matches || deleting}
            onClick={confirm}>Elimina</button>
        </div>
      </div>
    </div>
  );
}
