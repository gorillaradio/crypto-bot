import type { Position } from "../api";
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

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length)
    return <p className="empty">Nessuna posizione aperta — tutto il capitale è in cash.</p>;

  return (
    <div className="table-wrap">
      <table className="ptable num">
        <thead>
          <tr>
            <th>Coin</th>
            <th className="th-spark">Andamento 24h</th>
            <th>Quantità</th>
            <th>Prezzo medio</th>
            <th>Costo</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.symbol}>
              <td className="coin">{p.symbol.replace(/USDT$/, "")}</td>
              <td className="td-spark">
                <Sparkline symbol={p.symbol} />
              </td>
              <td>{qty(p.quantity)}</td>
              <td>{price(p.avg_price)}</td>
              <td>{usd(p.cost_basis)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
