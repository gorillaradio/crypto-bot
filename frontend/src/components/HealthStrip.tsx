import { useMemo } from "react";
import type { AgentEvent, DecisionPayload, ReflectionPayload, SkippedAction } from "../api";
import { isToday } from "@/lib/format";

/* Parametri vitali della macchina. Tre toni: grigio (normale), ambra (degrado),
   rosso (rottura). Mai verde: quello appartiene al profitto. */

const isDecision = (e: AgentEvent): e is AgentEvent & { payload: DecisionPayload } =>
  e.kind === "decision" && !!e.payload && "status" in e.payload && !("side" in e.payload);
const isReflection = (e: AgentEvent): e is AgentEvent & { payload: ReflectionPayload } =>
  e.kind === "reflection" && !!e.payload && "status" in e.payload;

function Item({ tone, children, title }: {
  tone: "ok" | "warn" | "err"; children: React.ReactNode; title?: string;
}) {
  return (
    <span className="strip-item">
      <span className={`dot dot-${tone}`} aria-hidden="true" />
      <span className={tone === "warn" ? "warn-t" : tone === "err" ? "err-t" : undefined} title={title}>
        {children}
      </span>
    </span>
  );
}

export function HealthStrip({ events, decisionSeconds }: {
  events: AgentEvent[]; decisionSeconds: number;
}) {
  const s = useMemo(() => {
    const lastDecision = events.find((e) => e.kind === "decision");
    const ageMin = lastDecision
      ? Math.floor((Date.now() - new Date(lastDecision.timestamp).getTime()) / 60000)
      : null;
    const stale = ageMin != null && ageMin * 60 > decisionSeconds * 1.5;

    const today = events.filter((e) => isToday(e.timestamp));
    const badReflections = today.filter(
      (e) => isReflection(e) && e.payload.status !== "ok");
    const decisionsToday = today.filter(isDecision);
    const skipped = decisionsToday.reduce((n, e) => n + (e.payload.skipped_count ?? 0), 0);
    const skipReasons = decisionsToday
      .flatMap((e) => e.payload.skipped ?? [])
      .map((sk: SkippedAction) => `${sk.reason}${sk.symbol ? ` (${sk.symbol.replace(/USDT$/, "")})` : ""}`);
    const errors = decisionsToday.reduce((n, e) => n + (e.payload.errors ?? 0), 0)
      + decisionsToday.filter((e) => e.payload.status === "error").length;
    return { ageMin, stale, badReflections, skipped, skipReasons, errors };
  }, [events, decisionSeconds]);

  const broken = s.stale || s.errors > 0;
  return (
    <div className={`strip${broken ? " is-broken" : ""}`} role="status" aria-label="Salute dell'agente">
      {s.ageMin == null ? (
        <Item tone="ok">nessun ciclo ancora</Item>
      ) : s.stale ? (
        <Item tone="err">loop fermo da {s.ageMin} min <span className="strip-hint">(atteso ogni ~{Math.round(decisionSeconds / 60)} min)</span></Item>
      ) : (
        <Item tone="ok">ultimo ciclo {s.ageMin} min fa</Item>
      )}
      {s.badReflections.length === 0 ? (
        <Item tone="ok">riflessioni ok</Item>
      ) : (
        <Item tone="warn" title={(s.badReflections[0].payload as ReflectionPayload).detail}>
          {s.badReflections.length} {s.badReflections.length === 1 ? "riflessione scartata" : "riflessioni scartate"} oggi
        </Item>
      )}
      <Item tone={s.skipped > 0 ? "warn" : "ok"} title={s.skipReasons.join(" · ") || undefined}>
        {s.skipped} saltate oggi
      </Item>
      <Item tone={s.errors > 0 ? "err" : "ok"}>
        {s.errors} {s.errors === 1 ? "errore" : "errori"}
      </Item>
    </div>
  );
}
