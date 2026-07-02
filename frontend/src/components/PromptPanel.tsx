import { useEffect, useState } from "react";
import { getPrompt, AuthError, type PromptPreview } from "../api";

const PIECES: { key: keyof PromptPreview; label: string }[] = [
  { key: "decision", label: "Decisione" },
  { key: "reflection", label: "Reflection" },
  { key: "retry", label: "Retry" },
];

export function PromptView({ preview }: { preview: PromptPreview }) {
  const [active, setActive] = useState<keyof PromptPreview>("decision");
  const pair = preview[active];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        {PIECES.map((p) => (
          <button
            key={p.key}
            onClick={() => setActive(p.key)}
            className={`text-xs px-2 py-1 rounded ${
              active === p.key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      {pair.note && <p className="text-xs text-muted-foreground">{pair.note}</p>}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">system</h3>
        <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-64 whitespace-pre-wrap">{pair.system}</pre>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">user</h3>
        <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-64 whitespace-pre-wrap">{pair.user}</pre>
      </div>
    </div>
  );
}

export function PromptPanel({ agentId }: { agentId: number }) {
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError(null);
    getPrompt(agentId)
      .then((p) => alive && setPreview(p))
      .catch((e) => alive && setError(e instanceof AuthError ? "Non autorizzato" : "Prompt non disponibile"));
    return () => {
      alive = false;
    };
  }, [agentId]);
  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!preview) return <p className="text-sm text-muted-foreground">Carico i prompt…</p>;
  return <PromptView preview={preview} />;
}
