import type { Position } from "../api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Sparkline } from "./Sparkline";

const usd = (s: string | number) =>
  `$${Number(s).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const price = (s: string) => {
  const n = Number(s);
  if (n >= 1) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toPrecision(2)}`; // sub-cent: keep significant figures (e.g. $0.0000024)
};
const qty = (s: string) => {
  const n = Number(s);
  return n >= 1 ? n.toLocaleString("en-US", { maximumFractionDigits: 4 })
                : n.toLocaleString("en-US", { maximumFractionDigits: 8 });
};

// Shared cell classes: original .ptable th/td — right-aligned, nowrap, tabular-nums mono
const thBase = "text-right text-[12px] font-medium text-muted-foreground whitespace-nowrap py-0 pb-[8px] px-0";
const tdBase = "text-right whitespace-nowrap py-[8px] px-0 border-t border-border border-b-0 tabular-nums font-mono";
// Sparkline column: left-aligned, 16px horizontal padding (original .th-spark/.td-spark)
const thSpark = "text-left pl-[16px] pr-[16px]";
const tdSpark = "text-left pl-[16px] pr-[16px]";

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length)
    return <p className="empty">Nessuna posizione aperta — tutto il capitale è in cash.</p>;

  return (
    // Table primitive already wraps in overflow-x-auto; we add border-collapse via
    // [border-collapse:collapse] since shadcn uses separate borders by default.
    <Table className="[border-collapse:collapse] tabular-nums font-mono">
      <TableHeader className="[&_tr]:border-b-0">
        <TableRow className="border-0 hover:bg-transparent">
          {/* First column: left-aligned (original .ptable th:first-child) */}
          <TableHead className={`${thBase} text-left`}>Coin</TableHead>
          <TableHead className={`${thBase} ${thSpark}`}>Andamento 24h</TableHead>
          <TableHead className={thBase}>Quantità</TableHead>
          <TableHead className={thBase}>Prezzo medio</TableHead>
          <TableHead className={thBase}>Costo</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="[&_tr:last-child]:border-0">
        {positions.map((p) => (
          <TableRow key={p.symbol} className="border-0 hover:bg-transparent">
            {/* First column: left-aligned, bold coin name (original .coin) */}
            <TableCell className={`${tdBase} text-left font-semibold`}>
              {p.symbol.replace(/USDT$/, "")}
            </TableCell>
            <TableCell className={`${tdBase} ${tdSpark}`}>
              <Sparkline symbol={p.symbol} />
            </TableCell>
            <TableCell className={tdBase}>{qty(p.quantity)}</TableCell>
            <TableCell className={tdBase}>{price(p.avg_price)}</TableCell>
            <TableCell className={tdBase}>{usd(p.cost_basis)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
