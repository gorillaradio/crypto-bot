import { useState } from "react";
import { createAgent, updateAgent, type Agent, type AgentCreateInput } from "../api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props =
  | { mode: "create"; onClose: () => void; onSaved: (a: Agent) => void }
  | { mode: "edit"; agent: Agent; onClose: () => void; onSaved: (a: Agent) => void };

export function AgentFormModal(props: Props) {
  const isEdit = props.mode === "edit";
  const [name, setName] = useState(isEdit ? props.agent.name : "");
  const [instructions, setInstructions] = useState("");
  const [durationDays, setDurationDays] = useState(7);
  const [modelName, setModelName] = useState("");
  const [universe, setUniverse] = useState<"TOP_50" | "TOP_100">("TOP_100");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const valid = name.trim().length > 0 &&
    (isEdit || (durationDays >= 1 && modelName.trim().length > 0));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    try {
      if (isEdit) {
        const a = await updateAgent(props.agent.id, { name: name.trim() });
        props.onSaved(a);
      } else {
        const payload: AgentCreateInput = {
          name: name.trim(),
          instructions,
          duration_days: durationDays,
          model_name: modelName.trim(),
          universe,
        };
        const a = await createAgent(payload);
        props.onSaved(a);
      }
    } catch {
      setError(isEdit ? "modifica fallita" : "creazione fallita");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) props.onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Modifica agente" : "Nuovo agente"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="agent-name">Nome</Label>
            <Input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>

          {!isEdit && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-instructions">Istruzioni</Label>
                <Textarea id="agent-instructions" value={instructions}
                  onChange={(e) => setInstructions(e.target.value)} rows={3} />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-duration">Durata (giorni)</Label>
                <Input id="agent-duration" type="number" min={1} value={durationDays}
                  onChange={(e) => setDurationDays(Number(e.target.value))} />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-model">Modello (OpenRouter)</Label>
                <Input id="agent-model" value={modelName}
                  onChange={(e) => setModelName(e.target.value)} placeholder="es. deepseek/deepseek-v4-flash" />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-universe">Universo</Label>
                <Select value={universe} onValueChange={(v) => setUniverse(v as "TOP_50" | "TOP_100")}>
                  <SelectTrigger id="agent-universe" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="TOP_100">Top 100</SelectItem>
                    <SelectItem value="TOP_50">Top 50</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {isEdit && (
            <p className="text-sm text-muted-foreground">Solo il nome è modificabile: gli altri parametri
              definiscono il comportamento e restano fissi per l'intera run.</p>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={props.onClose}>Annulla</Button>
            <Button type="submit" disabled={!valid || saving}>
              {isEdit ? "Salva" : "Crea"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
