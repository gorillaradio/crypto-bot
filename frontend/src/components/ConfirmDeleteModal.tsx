import { useState } from "react";
import { deleteAgent, type Agent } from "../api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

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
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Elimina «{agent.name}»</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">Questa azione è irreversibile. Verranno cancellati definitivamente posizioni,
            operazioni, equity, eventi e memoria di questo agente.</p>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirm-name">Scrivi <b>{agent.name}</b> per confermare</Label>
            <Input id="confirm-name" value={confirmText} autoFocus
              onChange={(e) => setConfirmText(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Annulla</Button>
          <Button type="button" variant="destructive" disabled={!matches || deleting}
            onClick={confirm}>Elimina</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
