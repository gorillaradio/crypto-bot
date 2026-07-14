import { useEffect, useRef, useState } from "react";

import { AuthError, getLifecycleDetail, type LifecycleDetail, type LifecycleMarket } from "../api";
import { Button } from "@/components/ui/button";
import { dayShort, hm, pct, usd } from "@/lib/format";

type Props = {
  agentId: number;
  lifecycleId: string;
  onClose: () => void;
  onAuthLost: () => void;
};

type RequestState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; detail: LifecycleDetail };

const dateTime = (value: string) => `${dayShort(value)} ${hm(value)}`;
const money = (value: string | null) => value == null ? "—" : usd(value);
const signedMoney = (value: string | null) => {
  if (value == null) return "—";
  const amount = Number(value);
  return `${amount >= 0 ? "+" : "−"}${usd(Math.abs(amount))}`;
};

function MarketDisclosure({ market }: { market: LifecycleMarket }) {
  if (market.status === "fresh")
    return <p className="text-xs pos" aria-live="polite">Dati di mercato aggiornati.</p>;
  if (market.status === "stale")
    return (
      <p className="text-xs text-[var(--warn)]" aria-live="polite">
        Dati di mercato non aggiornati. Ultimo aggiornamento: {market.as_of ? dateTime(market.as_of) : "non disponibile"}.
      </p>
    );
  return <p className="text-xs neg" aria-live="polite">Dati di mercato non disponibili.</p>;
}

function Evaluation({ detail }: { detail: LifecycleDetail }) {
  const evaluation = detail.evaluation;
  if (!evaluation)
    return <p className="text-sm text-muted-foreground">Nessuna valutazione esplicita registrata</p>;

  const alignment = {
    follows: "Segue la policy",
    violates: "Viola la policy",
    unrelated: "Non correlata alla policy",
  }[evaluation.policy_alignment];

  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
      <dt className="text-muted-foreground">Azione</dt>
      <dd className="font-mono font-semibold">{evaluation.action}</dd>
      <dt className="text-muted-foreground">Razionale</dt>
      <dd className="max-w-[72ch]">{evaluation.rationale ?? "Nessun razionale registrato"}</dd>
      <dt className="text-muted-foreground">Valutata</dt>
      <dd className="num">{dateTime(evaluation.timestamp)}</dd>
      <dt className="text-muted-foreground">Policy</dt>
      <dd className="flex flex-wrap items-center gap-2">
        <span>{alignment}</span>
        {evaluation.policy_refs.map(ref => <span key={ref} className="chip num">{ref}</span>)}
      </dd>
      {evaluation.override_reason && (
        <>
          <dt className="text-muted-foreground">Override</dt>
          <dd>{evaluation.override_reason}</dd>
        </>
      )}
    </dl>
  );
}

function Economy({ detail }: { detail: LifecycleDetail }) {
  const { economy, market } = detail;
  const marketAvailable = market.status !== "unavailable";
  const net = marketAvailable && economy.net_result_usd != null && economy.net_result_pct != null
    ? `${signedMoney(economy.net_result_usd)} · ${pct(economy.net_result_pct)}`
    : "—";

  return (
    <dl className="grid grid-cols-[minmax(8rem,1fr)_auto] gap-x-6 gap-y-2 text-sm sm:grid-cols-[minmax(8rem,1fr)_auto_minmax(8rem,1fr)_auto]">
      <dt className="font-medium">Risultato netto</dt>
      <dd className="num text-right font-semibold">{net}</dd>
      <dt className="text-muted-foreground">Realizzato</dt>
      <dd className="num text-right">{signedMoney(economy.realized_usd)}</dd>
      <dt className="text-muted-foreground">Non realizzato</dt>
      <dd className="num text-right">{marketAvailable ? signedMoney(economy.unrealized_usd) : "—"}</dd>
      <dt className="text-muted-foreground">Fee</dt>
      <dd className="num text-right">{usd(economy.fees_usd)}</dd>
      <dt className="text-muted-foreground">Investito</dt>
      <dd className="num text-right">{usd(economy.invested_usd)}</dd>
      <dt className="text-muted-foreground">Esposizione</dt>
      <dd className="num text-right">{marketAvailable ? money(economy.exposure_usd) : "—"}</dd>
      <dt className="text-muted-foreground">Quantità</dt>
      <dd className="num text-right">{economy.quantity}</dd>
      <dt className="text-muted-foreground">Prezzo medio</dt>
      <dd className="num text-right">{usd(economy.avg_price)}</dd>
      <dt className="text-muted-foreground">Ultimo prezzo</dt>
      <dd className="num text-right">{marketAvailable ? money(economy.last_price) : "—"}</dd>
    </dl>
  );
}

function Accounting({ detail }: { detail: LifecycleDetail }) {
  return (
    <details className="border-t border-border pt-3 text-sm">
      <summary className="w-fit cursor-pointer font-medium focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        Contabilità
      </summary>
      <div className="mt-3">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="pb-2 font-medium">Ora</th>
              <th scope="col" className="pb-2 font-medium">Lato</th>
              <th scope="col" className="pb-2 text-right font-medium">Quantità</th>
              <th scope="col" className="pb-2 text-right font-medium">Prezzo</th>
              <th scope="col" className="pb-2 text-right font-medium">Fee</th>
            </tr>
          </thead>
          <tbody>
            {detail.trades.map(trade => (
              <tr key={trade.id} className="border-t border-border font-mono tabular-nums">
                <td className="py-2 pr-4">{dateTime(trade.timestamp)}</td>
                <td className={`py-2 pr-4 font-semibold ${trade.side === "BUY" ? "pos" : "neg"}`}>{trade.side}</td>
                <td className="py-2 pl-4 text-right">{trade.quantity}</td>
                <td className="py-2 pl-4 text-right">{usd(trade.price)}</td>
                <td className="py-2 pl-4 text-right">{usd(trade.fee)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function OpenLifecycleDetail({ agentId, lifecycleId, onClose, onAuthLost }: Props) {
  const request = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<RequestState>({ kind: "loading" });

  useEffect(() => {
    const current = ++request.current;
    setState({ kind: "loading" });
    getLifecycleDetail(agentId, lifecycleId).then(
      detail => { if (request.current === current) setState({ kind: "ready", detail }); },
      error => {
        if (request.current !== current) return;
        if (error instanceof AuthError) onAuthLost();
        else setState({ kind: "error" });
      },
    );
    return () => { request.current += 1; };
  }, [agentId, lifecycleId, attempt, onAuthLost]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    if (state.kind === "ready") headingRef.current?.focus();
  }, [state]);

  if (state.kind === "loading")
    return <p role="status" className="py-4 text-sm text-muted-foreground">Caricamento dettaglio…</p>;

  if (state.kind === "error")
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 py-4 text-sm">
        <span>Dettaglio non disponibile.</span>
        <Button type="button" variant="outline" size="sm" onClick={() => setAttempt(value => value + 1)}>
          Riprova
        </Button>
      </div>
    );

  const { detail } = state;
  const symbol = detail.symbol.replace(/USDT$/, "");

  return (
    <section aria-labelledby="open-lifecycle-detail-heading" className="space-y-5 border-t border-border pt-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2
            ref={headingRef}
            id="open-lifecycle-detail-heading"
            tabIndex={-1}
            className="text-base font-semibold focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Dettaglio {symbol}
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Aperta {dateTime(detail.opened_at)} · ultima variazione {dateTime(detail.last_changed_at)}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>Chiudi</Button>
      </header>

      <section aria-labelledby="open-lifecycle-evaluation-heading" className="space-y-3 border-t border-border pt-3">
        <h3 id="open-lifecycle-evaluation-heading" className="text-sm font-semibold">Valutazione esplicita</h3>
        <Evaluation detail={detail} />
      </section>

      <section aria-labelledby="open-lifecycle-economy-heading" className="space-y-3 border-t border-border pt-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="open-lifecycle-economy-heading" className="text-sm font-semibold">Economia</h3>
          <MarketDisclosure market={detail.market} />
        </div>
        <Economy detail={detail} />
      </section>

      <Accounting detail={detail} />
    </section>
  );
}
