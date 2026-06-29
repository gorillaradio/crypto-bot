import { useEffect, useState } from "react";
import { listShareLinks, createShareLink, revokeShareLink, type ShareLink } from "../api";

export function ShareLinksModal({ onClose }: { onClose: () => void }) {
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [label, setLabel] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => listShareLinks().then(setLinks).catch(() => setError("caricamento fallito"));
  useEffect(() => { reload(); }, []);

  async function create() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await createShareLink(label.trim() || undefined);
      setLabel("");
      await reload();
    } catch {
      setError("creazione fallita");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: number) {
    setError("");
    try {
      await revokeShareLink(id);
      await reload();
    } catch {
      setError("revoca fallita");
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>Condividi (sola lettura)</h2>
        <p className="modal-note">Crea link segreti per dare accesso in sola lettura. Ogni link
          è revocabile in qualsiasi momento.</p>
        <div className="share-create">
          <input value={label} placeholder="etichetta (opzionale)"
            onChange={(e) => setLabel(e.target.value)} />
          <button type="button" className="btn-primary" onClick={create} disabled={busy}>Crea link</button>
        </div>
        {error && <p className="modal-error">{error}</p>}
        <ul className="share-list">
          {links.map((l) => (
            <li key={l.id} className="share-row">
              <div className="share-meta">
                <span className="share-label">{l.label || "senza etichetta"}</span>
                <input className="share-url" readOnly value={l.url}
                  onFocus={(e) => e.currentTarget.select()} />
              </div>
              <button type="button" className="btn-ghost danger" onClick={() => revoke(l.id)}>revoca</button>
            </li>
          ))}
          {!links.length && <li className="empty">Nessun link attivo.</li>}
        </ul>
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Chiudi</button>
        </div>
      </div>
    </div>
  );
}
