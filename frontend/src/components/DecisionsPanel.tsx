import type { Decision } from "../api";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const time = (t: string) =>
  new Date(t).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

// parsed_output è un Decision JSON solo per kind === "decision"
// (reflection/distillation portano altre forme) → riassunto "TYPE SYMBOL", o "—".
function actionsSummary(d: Decision): string {
  if (d.kind !== "decision" || !d.parsed_output) return "—";
  try {
    const parsed = JSON.parse(d.parsed_output) as { actions?: { type: string; symbol?: string | null }[] };
    const acts = parsed.actions ?? [];
    if (!acts.length) return "nessuna azione";
    return acts.map((a) => `${a.type}${a.symbol ? " " + a.symbol.replace(/USDT$/, "") : ""}`).join(", ");
  } catch {
    return "—";
  }
}

const tag = "text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground";

export function DecisionsPanel({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <p className="empty">Ancora nessuna decisione registrata.</p>;
  return (
    <Table className="tabular-nums">
      <TableHeader>
        <TableRow>
          <TableHead className="text-left text-xs">Quando</TableHead>
          <TableHead className="text-left text-xs">Tipo</TableHead>
          <TableHead className="text-left text-xs">Trigger</TableHead>
          <TableHead className="text-left text-xs">Azioni</TableHead>
          <TableHead className="text-left text-xs">Modello</TableHead>
          <TableHead className="text-right text-xs">Latenza</TableHead>
          <TableHead className="text-left text-xs">Parse</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {decisions.map((d) => (
          <TableRow key={d.id}>
            <TableCell className="text-left text-xs whitespace-nowrap">{time(d.created_at)}</TableCell>
            <TableCell className="text-left"><span className={tag}>{d.kind}</span></TableCell>
            <TableCell className="text-left"><span className={tag}>{d.trigger}</span></TableCell>
            <TableCell className="text-left text-xs">{actionsSummary(d)}</TableCell>
            <TableCell className="text-left text-xs">{d.model_name ?? "—"}</TableCell>
            <TableCell className="text-right text-xs">{d.latency_ms} ms</TableCell>
            <TableCell className="text-left"><span className={tag}>{d.parse_status}</span></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
