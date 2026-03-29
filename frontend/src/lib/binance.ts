export interface BinanceCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export async function fetchBinanceCandles(
  symbol: string,
  interval: string,
  limit: number = 500,
): Promise<BinanceCandle[]> {
  const url = `https://api.binance.com/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}`;
  const response = await fetch(url, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(`Binance request failed: ${response.status}`);
  }

  const raw = (await response.json()) as Array<[
    number,
    string,
    string,
    string,
    string,
    string,
    number,
    string,
    number,
    string,
    string,
    string,
  ]>;

  return raw.map((item) => ({
    time: Math.floor(item[0] / 1000),
    open: Number(item[1]),
    high: Number(item[2]),
    low: Number(item[3]),
    close: Number(item[4]),
  }));
}