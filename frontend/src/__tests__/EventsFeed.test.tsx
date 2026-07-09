import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EventsFeed } from "../components/EventsFeed";
import type { AgentEvent, EventPayload, PolicyLine } from "../api";

const ev = (
  kind: string, payload: EventPayload | null, cycle_id: string | null,
  timestamp = "2026-07-09T09:40:39Z", message = "raw message",
): AgentEvent => ({ timestamp, kind, message, cycle_id, payload });

const decision = (note: string, cycle: string, ts: string, extra: object = {}): AgentEvent =>
  ev("decision", { status: "ok", note, executed: 0, skipped: [], skipped_count: 0,
                   errors: 0, trigger: "schedule", wake_reason: null, ...extra }, cycle, ts);

const POLICY: PolicyLine[] = [{ ref: "P3329", content: "Take profit oltre +12% sulle micro-cap" }];

describe("EventsFeed (payload-driven)", () => {
  it("raggruppa i cicli fermi consecutivi in un blocco unico con la nota più recente", () => {
    const events = [
      decision("waiting for setups", "c3", "2026-07-09T10:34:00Z"),
      decision("still cautious", "c2", "2026-07-09T10:29:00Z"),
      decision("buys ACT", "c1", "2026-07-09T10:21:00Z", { executed: 1 }),
    ];
    // c1 ha un trade → non raggruppabile
    events.push(ev("trade", { side: "BUY", symbol: "ACTUSDT", qty: "378", price: "0.0132",
                              fee: "0.005", usd_value: "5", rationale: "momentum",
                              position: "new" }, "c1", "2026-07-09T10:21:01Z"));
    const { container } = render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText(/nessuna mossa/i)).toBeInTheDocument();
    expect(screen.getByText(/2 cicli/)).toBeInTheDocument();
    expect(screen.getByText(/waiting for setups/)).toBeInTheDocument();   // nota più recente
    expect(container.textContent).toContain("10:29");                     // range orario
  });

  it("vendita: pill neutra, P&L colorato, quota solo se parziale", () => {
    const events = [
      decision("lock profits", "c1", "2026-07-09T10:21:00Z", { executed: 2 }),
      ev("trade", { side: "SELL", symbol: "SPELLUSDT", qty: "144788", price: "0.00012",
                    fee: "0.01", usd_value: "17", rationale: "target exceeded per P3329",
                    fraction: "0.5", avg_cost: "0.000104",
                    realized_pnl_pct: "15.2", realized_pnl_usd: "2.20" }, "c1"),
      ev("trade", { side: "SELL", symbol: "SYNUSDT", qty: "48.79", price: "0.4626",
                    fee: "0.02", usd_value: "22", rationale: "same", fraction: "1",
                    avg_cost: "0.4054", realized_pnl_pct: "14.1",
                    realized_pnl_usd: "2.80" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={POLICY} />);
    expect(screen.getAllByText("VENDITA")).toHaveLength(2);
    expect(screen.getByText(/venduto il 50%/)).toBeInTheDocument();
    expect(screen.queryByText(/venduto il 100%/)).not.toBeInTheDocument();
    const pnl = screen.getByText(/\+15[.,]20%/);   // pct() formatta a 2 decimali
    expect(pnl.closest(".pos")).not.toBeNull();
    // la pill non deve avere classi di colore esito
    const pill = screen.getAllByText("VENDITA")[0];
    expect(pill.className).not.toMatch(/pos|neg/);
  });

  it("acquisto: valore grigio e natura della posizione, nessun P&L", () => {
    const events = [
      decision("entering", "c1", "2026-07-09T10:10:00Z", { executed: 1 }),
      ev("trade", { side: "BUY", symbol: "SPELLUSDT", qty: "289575", price: "0.000103",
                    fee: "0.03", usd_value: "29", rationale: "momentum",
                    position: "new" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText("ACQUISTO")).toBeInTheDocument();
    expect(screen.getByText(/nuova posizione/)).toBeInTheDocument();
    expect(screen.getByText(/~\$29/)).toBeInTheDocument();
  });

  it("il PERCHÉ cita la nota e risolve i riferimenti policy in tooltip", () => {
    const events = [
      decision("exit per P3329 discipline", "c1", "2026-07-09T10:21:00Z", { executed: 1 }),
      ev("trade", { side: "SELL", symbol: "AUSDT", qty: "1", price: "2", fee: "0",
                    usd_value: "2", rationale: null, fraction: "1", avg_cost: "1",
                    realized_pnl_pct: "100", realized_pnl_usd: "1" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={POLICY} />);
    const ref = screen.getByText("P3329");
    expect(ref).toHaveAttribute("title", "Take profit oltre +12% sulle micro-cap");
  });

  it("niente eventi reflection nel diario; reasoning folded saltati", () => {
    const events = [
      ev("reflection", { status: "error", detail: "boom" }, "c1"),
      decision("note", "c1", "2026-07-09T10:00:00Z"),
      ev("reasoning", { raw: "folded thought", folded: true }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.queryByText(/riflessione/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
    expect(screen.queryByText(/folded thought/)).not.toBeInTheDocument();
  });

  it("ciclo in errore: fatto rosso con dettaglio", () => {
    render(<EventsFeed events={[
      ev("decision", { status: "error", detail: "timeout LLM", wake_reason: null }, "c1"),
    ]} policy={[]} />);
    expect(screen.getByText(/ciclo fallito/i)).toBeInTheDocument();
    expect(screen.getByText(/timeout LLM/)).toBeInTheDocument();
  });

  it("payload raw o assente: riga grezza smorzata", () => {
    render(<EventsFeed events={[
      ev("trade", { raw: "SELL strano non parsato" }, null),
      ev("decision", null, "c9", "2026-07-09T08:00:00Z", "messaggio antico"),
    ]} policy={[]} />);
    expect(screen.getByText(/SELL strano non parsato/)).toBeInTheDocument();
    expect(screen.getByText(/messaggio antico/)).toBeInTheDocument();
  });

  it("filtro 'solo operazioni' nasconde i gruppi d'attesa", () => {
    const events = [
      decision("wait", "c2", "2026-07-09T10:30:00Z"),
      decision("buys", "c1", "2026-07-09T10:00:00Z", { executed: 1 }),
      ev("trade", { side: "BUY", symbol: "AUSDT", qty: "1", price: "1", fee: "0",
                    usd_value: "1", rationale: null, position: "new" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText(/nessuna mossa/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /solo operazioni/i }));
    expect(screen.queryByText(/nessuna mossa/i)).not.toBeInTheDocument();
    expect(screen.getByText("ACQUISTO")).toBeInTheDocument();
  });

  it("risveglio e guardrail marcati, empty state invariato", () => {
    const { rerender } = render(<EventsFeed events={[
      decision("woke", "c1", "2026-07-09T10:00:00Z", { wake_reason: "breach BTC" }),
    ]} policy={[]} />);
    expect(screen.getByText("risveglio")).toBeInTheDocument();
    rerender(<EventsFeed events={[
      ev("trade", { side: "SELL", symbol: "BUSDT", qty: "1", price: "1", fee: "0",
                    usd_value: "1", rationale: null, fraction: "1", avg_cost: "2",
                    realized_pnl_pct: "-50", realized_pnl_usd: "-1" }, null),
    ]} policy={[]} />);
    expect(screen.getByText(/guardrail/i)).toBeInTheDocument();
    rerender(<EventsFeed events={[]} policy={[]} />);
    expect(screen.getByText(/nessuna attività/i)).toBeInTheDocument();
  });
});
