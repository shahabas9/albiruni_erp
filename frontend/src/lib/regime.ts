import { useAuth } from "../auth/AuthProvider";

/** The signed-in company's country: decides GST (India) or VAT (Saudi Arabia) screens. */
export function useCountry(): "IN" | "SA" {
  return useAuth().user?.country ?? "IN";
}

/** What the tax is called for this company. */
export function taxName(country: "IN" | "SA"): "GST" | "VAT" {
  return country === "SA" ? "VAT" : "GST";
}

/** Saudi VAT treatments for an item: the rate and ZATCA category together. */
export const SA_TREATMENTS = [
  { key: "S", label: "Standard rated — 15%", rate: 15 },
  { key: "Z", label: "Zero rated — 0%", rate: 0 },
  { key: "E", label: "Exempt", rate: 0 },
  { key: "O", label: "Out of scope", rate: 0 },
] as const;

/** ZATCA reason codes for zero-rated, exempt and out-of-scope supplies. */
export const EXEMPTION_REASONS: Record<string, string> = {
  "VATEX-SA-29": "Financial services (Article 29)",
  "VATEX-SA-29-7": "Life insurance services (Article 29)",
  "VATEX-SA-30": "Real estate transactions (Article 30)",
  "VATEX-SA-32": "Export of goods",
  "VATEX-SA-33": "Export of services",
  "VATEX-SA-34-1": "International transport of goods",
  "VATEX-SA-34-2": "International transport of passengers",
  "VATEX-SA-34-3": "Services directly connected to international transport",
  "VATEX-SA-34-4": "Supply of qualifying means of transport",
  "VATEX-SA-34-5": "Services relating to goods or passenger transport",
  "VATEX-SA-35": "Medicines and medical equipment",
  "VATEX-SA-36": "Qualifying metals",
  "VATEX-SA-EDU": "Private education to citizens",
  "VATEX-SA-HEA": "Private healthcare to citizens",
  "VATEX-SA-OOS": "Out of scope",
};
