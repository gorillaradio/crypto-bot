import { Fragment, useState } from "react";
import type { AgentEvent, OpenLifecycle, TradePayload } from "../api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Sparkline } from "./Sparkline";
import { dayShort, hm, price, pct, qty, usd } from "@/lib/format";

// Shared cell classes: original .ptable th/td — right-aligned, nowrap, tabular-nums mono
const thBase = "text-right text-xs font-medium text-muted-foreground whitespace-nowrap py-0 pb-2 px-0";
const tdBase = "text-right whitespace-nowrap py-2 px-0 border-t border-border border-b-0 tabular-nums font-mono";
// Sparkline column: left-aligned, 16px horizontal padding (original .th-spark/.td-spark)
const thSpark = "text-left pl-4 pr-4";
const tdSpark = "text-left pl-4 pr-4";

// Racconto sintetico della vita della posizione dai trade events del symbol: SELL
// parziale ("−N% alle HH:MM") e BUY di rincalzo ("aumentata alle HH:MM"), in ordine
// cronologico. Nessuna posizione ha un cycle_id di apertura da agganciare qui.
function storia(events: AgentEvent[], symbol: string, openedAt: string | null): string {
  if (!openedAt) return "—";
  const items: string[] = [];
  for (const e of [...events].reverse()) {           // eventi desc → cronologico
    if (e.kind !== "trade" || !e.payload || !("side" in e.payload)) continue;
    const p = e.payload as TradePayload;
    if (p.symbol !== symbol || e.timestamp < openedAt) continue;
    if (p.side === "SELL" && p.fraction != null && Number(p.fraction) < 0.995)
      items.push(`−${Math.round(Number(p.fraction) * 100)}% alle ${hm(e.timestamp)}`);
    if (p.side === "BUY" && p.position === "increase")
      items.push(`aumentata alle ${hm(e.timestamp)}`);
  }
  return items.length ? items.join(" · ") : "—";
}

export function PositionsTable({ positions, events }: { positions: OpenLifecycle[]; events: AgentEvent[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (!positions.length)
    return <p className="empty">Nessuna posizione aperta — tutto il capitale è in cash.</p>;

  const toggle = (lifecycleId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(lifecycleId)) next.delete(lifecycleId);
      else next.add(lifecycleId);
      return next;
    });

  return (
    // Table primitive already wraps in overflow-x-auto; we add border-collapse via
    // [border-collapse:collapse] since shadcn uses separate borders by default.
    <Table className="[border-collapse:collapse] tabular-nums font-mono">
      <TableHeader className="[&_tr]:border-b-0">
        <TableRow className="border-0 hover:bg-transparent">
          {/* First column: left-aligned (original .ptable th:first-child) */}
          <TableHead className={`${thBase} text-left`}>Coin</TableHead>
          <TableHead className={`${thBase} ${thSpark}`}>Andamento 24h</TableHead>
          <TableHead className={thBase}>Valore</TableHead>
          <TableHead className={thBase}>Risultato netto</TableHead>
          <TableHead className={thBase}>Già incassato</TableHead>
          <TableHead className={thBase} aria-hidden="true" />
        </TableRow>
      </TableHeader>
      <TableBody className="[&_tr:last-child]:border-0">
        {positions.map((p) => {
          const sym = p.symbol.replace(/USDT$/, "");
          const isOpen = expanded.has(p.lifecycle_id);
          const realized = Number(p.realized_usd);
          const story = storia(events, p.symbol, p.opened_at);
          return (
            <Fragment key={p.lifecycle_id}>
              <TableRow
                id={`pos-${p.lifecycle_id}`}
                className="border-0 hover:bg-transparent cursor-pointer"
                onClick={() => toggle(p.lifecycle_id)}
              >
                {/* First column: left-aligned, bold coin name (original .coin) */}
                <TableCell className={`${tdBase} text-left font-semibold`}>
                  {sym}
                  {p.opened_at && (
                    <div className="text-xs font-normal text-muted-foreground">
                      aperta {dayShort(p.opened_at)} {hm(p.opened_at)}
                    </div>
                  )}
                </TableCell>
                <TableCell className={`${tdBase} ${tdSpark}`}>
                  <Sparkline symbol={p.symbol} />
                </TableCell>
                <TableCell className={tdBase}>{p.exposure_usd == null ? "—" : usd(p.exposure_usd)}</TableCell>
                <TableCell className={tdBase}>
                  {p.net_result_pct == null ? "—" : (
                    <span className={Number(p.net_result_pct) >= 0 ? "pos" : "neg"}>
                      {pct(p.net_result_pct)}
                    </span>
                  )}
                </TableCell>
                <TableCell className={tdBase}>
                  {realized === 0 ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <span className={realized >= 0 ? "pos" : "neg"}>
                      {realized >= 0 ? "+" : "−"}{usd(Math.abs(realized))}
                    </span>
                  )}
                </TableCell>
                <TableCell className={`${tdBase} pl-2`}>
                  <button
                    type="button"
                    aria-label="dettagli"
                    aria-expanded={isOpen}
                    className="bg-transparent border-0 cursor-pointer p-0 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(p.lifecycle_id);
                    }}
                  >
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                </TableCell>
              </TableRow>
              {isOpen && (
                <TableRow className="border-0 hover:bg-transparent">
                  {/* La tabella racconta, il dettaglio rende conto: storia e numeri da contabile qui soltanto. */}
                  <TableCell
                    colSpan={6}
                    className="text-left text-xs text-muted-foreground whitespace-normal py-2 px-0 border-t border-border"
                  >
                    {story !== "—" && <div>storia: {story}</div>}
                    quantità {qty(p.quantity)} · costo medio {price(p.avg_price)} · prezzo attuale{" "}
                    {p.last_price == null ? "—" : price(p.last_price)} · costo totale {usd(p.cost_basis)} · fee {usd(p.fees_usd)}
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
