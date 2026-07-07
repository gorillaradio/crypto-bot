// Shared formatters for the data tables and feeds. Money keeps the en-US "$1,234.56"
// convention already used across the dashboard; dates/times speak it-IT like the rest
// of the UI copy.

export const usd = (s: string | number) =>
  `$${Number(s).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const price = (s: string | number) => {
  const n = Number(s);
  if (n >= 1) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toPrecision(2)}`; // sub-cent: keep significant figures (e.g. $0.0000024)
};

export const qty = (s: string | number) => {
  const n = Number(s);
  return n >= 1 ? n.toLocaleString("en-US", { maximumFractionDigits: 4 })
                : n.toLocaleString("en-US", { maximumFractionDigits: 8 });
};

export const pct = (s: string | number) => {
  const n = Number(s);
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}%`;
};

/** "14:32" — feed/table time-of-day. */
export const hm = (t: string) =>
  new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

export const isToday = (t: string) => sameDay(new Date(t), new Date());

/** "oggi" | "ieri" | "5 luglio" (+ anno se non corrente) — separatori di giorno nei feed. */
export function dayLabel(t: string): string {
  const d = new Date(t);
  const now = new Date();
  if (sameDay(d, now)) return "oggi";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, yesterday)) return "ieri";
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "long" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("it-IT", opts);
}

/** "5 lug" — prefisso compatto di data nelle righe tabella. */
export const dayShort = (t: string) =>
  new Date(t).toLocaleDateString("it-IT", { day: "numeric", month: "short" });
