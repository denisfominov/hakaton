import { texts } from "./texts";

const short = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const integers = new Intl.NumberFormat("ru-RU");

export function rubles(value: number | null) {
  if (value === null) return texts.noData;
  if (value >= 1e9) return `${short.format(value / 1e9)} ${texts.units.billion}`;
  if (value >= 1e6) return `${short.format(value / 1e6)} ${texts.units.million}`;
  return `${integers.format(value)} ${texts.units.rub}`;
}

export const count = (value: number) => integers.format(value);
