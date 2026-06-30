import { useEffect, useState } from "react";
import { listShareLinks, createShareLink, revokeShareLink, type ShareLink } from "../api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

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
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Condividi (sola lettura)</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">Crea link segreti per dare accesso in sola lettura. Ogni link
            è revocabile in qualsiasi momento.</p>
          <div className="flex gap-2">
            <Input value={label} placeholder="etichetta (opzionale)"
              onChange={(e) => setLabel(e.target.value)} />
            <Button type="button" onClick={create} disabled={busy}>Crea link</Button>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <ul className="flex flex-col gap-2">
            {links.map((l) => (
              <li key={l.id} className="flex items-center gap-2">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-sm font-medium">{l.label || "senza etichetta"}</span>
                  <Input readOnly value={l.url}
                    onFocus={(e) => e.currentTarget.select()} />
                </div>
                <Button type="button" variant="outline" size="sm" onClick={() => revoke(l.id)}>revoca</Button>
              </li>
            ))}
            {!links.length && <li className="text-sm text-muted-foreground">Nessun link attivo.</li>}
          </ul>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Chiudi</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
