import type { Trade } from "../api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usd, price, qty, hm, dayShort, isToday } from "@/lib/format";

// Same cell idiom as PositionsTable: right-aligned nowrap mono numbers, muted headers.
const th = "text-right text-xs font-medium text-muted-foreground whitespace-nowrap py-0 pb-2 px-0";
const td = "text-right whitespace-nowrap py-2 px-0 border-t border-border border-b-0 tabular-nums font-mono";

export function TradesTable({ trades }: { trades: Trade[] }) {
  if (!trades.length)
    return <p className="empty">Ancora nessuna operazione: quando l'agente compra o vende la vedrai qui.</p>;

  return (
    <div className="max-h-[420px] overflow-y-auto">
      <Table className="[border-collapse:collapse] tabular-nums font-mono">
        <TableHeader className="[&_tr]:border-b-0">
          <TableRow className="border-0 hover:bg-transparent">
            <TableHead className={`${th} text-left`}>Quando</TableHead>
            <TableHead className={`${th} text-left`}>Op</TableHead>
            <TableHead className={`${th} text-left`}>Coin</TableHead>
            <TableHead className={th}>Quantità</TableHead>
            <TableHead className={th}>Prezzo</TableHead>
            <TableHead className={th}>Valore</TableHead>
            <TableHead className={th}>Fee</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className="[&_tr:last-child]:border-0">
          {trades.map((t) => (
            <TableRow key={t.id} className="border-0 hover:bg-transparent">
              <TableCell className={`${td} text-left pr-3 text-xs`}>
                {!isToday(t.timestamp) && (
                  <span className="text-muted-foreground">{dayShort(t.timestamp)} </span>
                )}
                {hm(t.timestamp)}
              </TableCell>
              <TableCell className={`${td} text-left pr-2`}>
                <span className={`tag ${t.side === "BUY" ? "buy" : "sell"}`}>{t.side}</span>
              </TableCell>
              <TableCell className={`${td} text-left font-semibold`}>
                {t.symbol.replace(/USDT$/, "")}
              </TableCell>
              <TableCell className={td}>{qty(t.quantity)}</TableCell>
              <TableCell className={td}>{price(t.price)}</TableCell>
              <TableCell className={td}>{usd(Number(t.quantity) * Number(t.price))}</TableCell>
              <TableCell className={`${td} text-muted-foreground`}>{price(t.fee)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
