/**
 * Phone helpers for Indian numbers: "94460 44556", "+91-9446044556" and
 * "09446044556" all become 919446044556.
 */
export function internationalDigits(phone: string): string | null {
  let digits = phone.replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length === 10) digits = `91${digits}`;
  return digits.length >= 11 && digits.length <= 15 ? digits : null;
}

export const telHref = (phone: string) => {
  const digits = internationalDigits(phone);
  return digits ? `tel:+${digits}` : `tel:${phone.replace(/[^\d+]/g, "")}`;
};

export const whatsappHref = (phone: string) => {
  const digits = internationalDigits(phone);
  return digits ? `https://wa.me/${digits}` : null;
};
