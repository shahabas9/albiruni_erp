// The signed-in company's currency (INR for India, SAR for Saudi Arabia); set at sign-in.
// Amounts on screen follow it — the helpers keep their old names, they aren't India-only.
let currency = "INR";

export function setMoneyCurrency(code: string | null | undefined) {
  currency = code || "INR";
}

export function moneyCurrency(): string {
  return currency;
}

function prefix(): string {
  return currency === "INR" ? "₹" : `${currency} `;
}

/** What sales tax is called for the signed-in company: GST (India) or VAT (Saudi Arabia). */
export function taxLabel(): "GST" | "VAT" {
  return currency === "INR" ? "GST" : "VAT";
}

/** "₹" or "SAR ", to put before a plain number. */
export function currencySign(): string {
  return prefix();
}

/** "₹" or "SAR", for labels like "Price (₹)". */
export function currencyLabel(): string {
  return currency === "INR" ? "₹" : currency;
}

/** A plain amount to two decimals with the right digit grouping (no symbol). */
export function plainMoney(n: number): string {
  return n.toLocaleString(currency === "INR" ? "en-IN" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Charts: lakhs in India, thousands elsewhere. */
export function chartUnit(): { divisor: number; suffix: string; label: string } {
  return currency === "INR"
    ? { divisor: 100_000, suffix: "L", label: "₹ in Lakhs" }
    : { divisor: 1000, suffix: "K", label: `${currency} in thousands` };
}

/** Short amounts: ₹28.6L, ₹1.2Cr, ₹42,500 in India; SAR 28.6K, SAR 1.2M elsewhere. */
export function inrShort(amount: number): string {
  if (currency === "INR") {
    if (amount >= 10_000_000) return `₹${(amount / 10_000_000).toFixed(1)}Cr`;
    if (amount >= 100_000) return `₹${(amount / 100_000).toFixed(1)}L`;
    return `₹${Math.round(amount).toLocaleString("en-IN")}`;
  }
  if (amount >= 1_000_000) return `${prefix()}${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 100_000) return `${prefix()}${(amount / 1000).toFixed(0)}K`;
  return `${prefix()}${Math.round(amount).toLocaleString("en-US")}`;
}

/** An exact amount: ₹42,500.5 (Indian grouping) or SAR 42,500.50. */
export function inr(amount: number): string {
  if (currency === "INR") return `₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  return `${prefix()}${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function dateTime(iso: string | null): string {
  if (!iso) return "No due date";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "2 days overdue", "due today", "in 3 days". */
export function relativeDue(iso: string | null, now = new Date()): string {
  if (!iso) return "No due date";
  const day = 86_400_000;
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((startOf(new Date(iso)) - startOf(now)) / day);
  if (diff === 0) return new Date(iso) < now ? "due earlier today" : "due today";
  if (diff === 1) return "due tomorrow";
  if (diff === -1) return "1 day overdue";
  if (diff < 0) return `${-diff} days overdue`;
  return `due in ${diff} days`;
}

export function initials(name: string | undefined | null): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/** yyyy-mm-ddThh:mm for <input type="datetime-local">, in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function quoteStatusClass(status: string): string {
  if (status === "Sent" || status === "Accepted") return "status-confirmed";
  if (status === "Pending approval") return "status-pending";
  if (status === "Rejected") return "status-rejected";
  return "status-draft";
}

/** Badge class for any sales document status. */
export function docStatusClass(status: string): string {
  if (["Confirmed", "Delivered", "Issued", "Paid", "Accepted", "Sent", "Invoiced", "Credited"].includes(status)) return "status-confirmed";
  if (["Pending approval", "Partly delivered", "Partly paid", "Partly invoiced"].includes(status)) return "status-pending";
  if (["Cancelled", "Rejected", "Overdue", "Voided"].includes(status)) return "status-rejected";
  return "status-draft";
}

/** 2026-09-30 → 30 Sep 2026 (a date with no time of day). */
export function dayDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y!, m! - 1, d!).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Today as yyyy-mm-dd in local time. */
export function todayIso(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
