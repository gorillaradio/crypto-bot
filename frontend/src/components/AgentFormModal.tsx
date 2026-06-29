import { useState } from "react";
import { createAgent, updateAgent, type Agent, type AgentCreateInput } from "../api";

type Props =
  | { mode: "create"; onClose: () => void; onSaved: (a: Agent) => void }
  | { mode: "edit"; agent: Agent; onClose: () => void; onSaved: (a: Agent) => void };

const PROVIDERS = ["anthropic", "deepseek", "glm", "openrouter"] as const;

export function AgentFormModal(props: Props) {
  const isEdit = props.mode === "edit";
  const [name, setName] = useState(isEdit ? props.agent.name : "");
  const [instructions, setInstructions] = useState("");
  const [durationDays, setDurationDays] = useState(7);
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("anthropic");
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
          model_provider: provider,
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
    <div className="modal-overlay" onMouseDown={props.onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>{isEdit ? "Modifica agente" : "Nuovo agente"}</h2>
        <form onSubmit={submit}>
          <label htmlFor="agent-name">Nome</label>
          <input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />

          {!isEdit && (
            <>
              <label htmlFor="agent-instructions">Istruzioni</label>
              <textarea id="agent-instructions" value={instructions}
                onChange={(e) => setInstructions(e.target.value)} rows={3} />

              <label htmlFor="agent-duration">Durata (giorni)</label>
              <input id="agent-duration" type="number" min={1} value={durationDays}
                onChange={(e) => setDurationDays(Number(e.target.value))} />

              <label htmlFor="agent-provider">Provider</label>
              <select id="agent-provider" value={provider}
                onChange={(e) => setProvider(e.target.value as (typeof PROVIDERS)[number])}>
                {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>

              <label htmlFor="agent-model">Modello</label>
              <input id="agent-model" value={modelName}
                onChange={(e) => setModelName(e.target.value)} placeholder="es. claude-opus-4-8" />

              <label htmlFor="agent-universe">Universo</label>
              <select id="agent-universe" value={universe}
                onChange={(e) => setUniverse(e.target.value as "TOP_50" | "TOP_100")}>
                <option value="TOP_100">Top 100</option>
                <option value="TOP_50">Top 50</option>
              </select>
            </>
          )}

          {isEdit && (
            <p className="modal-note">Solo il nome è modificabile: gli altri parametri
              definiscono il comportamento e restano fissi per l'intera run.</p>
          )}

          {error && <p className="modal-error">{error}</p>}

          <div className="modal-actions">
            <button type="button" className="btn-ghost" onClick={props.onClose}>Annulla</button>
            <button type="submit" className="btn-primary" disabled={!valid || saving}>
              {isEdit ? "Salva" : "Crea"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
