import type { LifecycleMarket, LifecycleState, LifecycleSummary } from "../api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dayShort, hm, pct, usd } from "@/lib/format";
import { Sparkline } from "./Sparkline";

const th = "text-xs font-medium text-muted-foreground whitespace-nowrap py-0 pb-2 px-2 first:pl-0";
const thLeft = `${th} text-left`;
const thRight = `${th} text-right`;
const td = "whitespace-nowrap py-2 px-2 first:pl-0 border-t border-border border-b-0 tabular-nums font-mono";
const tdLeft = `${td} text-left`;
const tdRight = `${td} text-right`;

const dateTime = (value: string | null) => value ? `${dayShort(value)} ${hm(value)}` : "—";
const money = (value: string | null) => value == null ? "—" : usd(value);
const percent = (value: string | null) => value == null ? "—" : pct(value);
const duration = (minutes: number | null) => {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}g ${hours % 24}h`;
};
const age = (openedAt: string) => duration(Math.max(0, Math.floor((Date.now() - new Date(openedAt).getTime()) / 60000)));

function Result({ item }: { item: LifecycleSummary }) {
  if (item.net_result_usd == null || item.net_result_pct == null) return <>—</>;
  const positive = Number(item.net_result_usd) >= 0;
  return (
    <span className={positive ? "pos" : "neg"}>
      {positive ? "+" : "−"}{usd(Math.abs(Number(item.net_result_usd)))} · {percent(item.net_result_pct)}
    </span>
  );
}

function MarketDisclosure({ market }: { market: LifecycleMarket }) {
  if (market.status === "fresh")
    return <p className="mb-2 text-xs pos" aria-live="polite">Dati di mercato aggiornati.</p>;
  if (market.status === "stale")
    return <p className="mb-2 text-xs text-[var(--warn)]" aria-live="polite">Dato di mercato non aggiornato. Ultimo aggiornamento: {market.as_of ?? "non disponibile"}.</p>;
  return <p className="mb-2 text-xs neg" aria-live="polite">Dati di mercato non disponibili.</p>;
}

export function PositionsTable({ items, market, state }: { items: LifecycleSummary[]; market: LifecycleMarket; state: LifecycleState }) {
  if (!items.length) {
    const copy = state === "open"
      ? "Nessuna posizione aperta — tutto il capitale è in cash."
      : state === "closed"
        ? "Nessuna posizione chiusa nel periodo selezionato. Amplia il periodo o scegli tutto lo storico."
        : "Non esiste ancora alcun lifecycle. Comparirà qui dopo la prima apertura dell’agente.";
    return <><MarketDisclosure market={market} /><p className="empty">{copy}</p></>;
  }

  return (
    <>
      <MarketDisclosure market={market} />
      <Table className="[border-collapse:collapse] tabular-nums font-mono">
        <TableHeader className="[&_tr]:border-b-0">
          <TableRow className="border-0 hover:bg-transparent">
            <TableHead className={thLeft}>Coin</TableHead>
            <TableHead className={thLeft}>24h</TableHead>
            {state === "all" && <TableHead className={thLeft}>Stato</TableHead>}
            {state === "open" && <><TableHead className={thRight}>Età</TableHead><TableHead className={thRight}>Esposizione</TableHead><TableHead className={thRight}>Peso</TableHead></>}
            {state === "closed" && <><TableHead className={thRight}>Chiusa</TableHead><TableHead className={thRight}>Durata</TableHead><TableHead className={thRight}>Investito</TableHead></>}
            {state === "all" && <><TableHead className={thRight}>Ultima attività</TableHead><TableHead className={thRight}>Capitale</TableHead></>}
            <TableHead className={thRight}>Risultato netto</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className="[&_tr:last-child]:border-0">
          {items.map((item) => (
            <TableRow key={item.lifecycle_id} className="border-0 hover:bg-transparent">
              <TableCell className={`${tdLeft} font-semibold`}>{item.symbol.replace(/USDT$/, "")}</TableCell>
              <TableCell className={tdLeft}><Sparkline symbol={item.symbol} closes={item.market_series_24h?.map(Number) ?? null} /></TableCell>
              {state === "all" && <TableCell className={tdLeft}>{item.status === "open" ? "Aperta" : "Chiusa"}</TableCell>}
              {state === "open" && <><TableCell className={tdRight}>{age(item.opened_at)}</TableCell><TableCell className={tdRight}>{money(item.exposure_usd)}</TableCell><TableCell className={tdRight}>{percent(item.portfolio_weight_pct)}</TableCell></>}
              {state === "closed" && <><TableCell className={tdRight}>{dateTime(item.closed_at)}</TableCell><TableCell className={tdRight}>{duration(item.held_minutes)}</TableCell><TableCell className={tdRight}>{money(item.invested_usd)}</TableCell></>}
              {state === "all" && <><TableCell className={tdRight}>{dateTime(item.last_changed_at)}</TableCell><TableCell className={tdRight}>{money(item.status === "open" ? item.exposure_usd : item.invested_usd)}</TableCell></>}
              <TableCell className={tdRight}><Result item={item} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
