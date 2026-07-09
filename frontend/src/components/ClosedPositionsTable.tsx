import type { ClosedPosition } from "../api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usd, pct, hm, dayShort } from "@/lib/format";

const held = (m: number | null) =>
  m == null ? "—" : m < 60 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} ore` : `${Math.round(m / 1440)} g`;

const when = (t: string | null) => (t ? `${dayShort(t)} ${hm(t)}` : "?");

export function ClosedPositionsTable({ closed }: { closed: ClosedPosition[] }) {
  if (!closed.length) return <p className="empty">Nessuna posizione chiusa finora.</p>;
  return (
    <Table className="tabular-nums font-mono">
      <TableHeader>
        <TableRow>
          <TableHead className="text-left text-xs">Coin</TableHead>
          <TableHead className="text-left text-xs">Arco</TableHead>
          <TableHead className="text-right text-xs">Tenuta</TableHead>
          <TableHead className="text-right text-xs">Investito</TableHead>
          <TableHead className="text-right text-xs">Esito</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {(() => {
          const seen = new Set<string>();
          return closed.map((c, i) => {
            const usdVal = Number(c.realized_total_usd);
            const cls = usdVal >= 0 ? "pos" : "neg";
            const symbol = c.symbol.replace(/USDT$/, "");
            // La lista arriva dal più recente: solo la prima occorrenza per symbol
            // (la più recente) prende l'id, per il link dal diario.
            const isFirst = !seen.has(symbol);
            seen.add(symbol);
            return (
              <TableRow key={`${c.symbol}-${c.closed_at}-${i}`} id={isFirst ? `pos-closed-${symbol}` : undefined}>
                <TableCell className="text-left font-semibold">{symbol}</TableCell>
                <TableCell className="text-left text-xs">
                  {when(c.opened_at)} → {when(c.closed_at)}
                  {c.close_cycle_id != null && (
                    <div>
                      <a className="text-xs" href={`#cycle-${c.close_cycle_id}`}>perché chiusa ›</a>
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-right text-xs">{held(c.held_minutes)}</TableCell>
                <TableCell className="text-right text-xs">{c.invested_usd ? `~${usd(c.invested_usd)}` : "—"}</TableCell>
                <TableCell className="text-right text-xs">
                  <span className={cls}>
                    {c.realized_total_pct != null && `${pct(c.realized_total_pct)} `}
                    ({usdVal >= 0 ? "+" : "−"}{usd(Math.abs(usdVal))})
                  </span>
                </TableCell>
              </TableRow>
            );
          });
        })()}
      </TableBody>
    </Table>
  );
}
