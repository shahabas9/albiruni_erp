/** ₹ in Indian units: ₹28.6L, ₹1.2Cr, ₹42,500. */
export function inrShort(amount: number): string {
  if (amount >= 10_000_000) return `₹${(amount / 10_000_000).toFixed(1)}Cr`;
  if (amount >= 100_000) return `₹${(amount / 100_000).toFixed(1)}L`;
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

export function inr(amount: number): string {
  return `₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
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
