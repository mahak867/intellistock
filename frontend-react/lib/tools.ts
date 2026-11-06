// Schema for the Tools hub: each tool is a form that builds a request body and posts it to the API.
export type FieldType = "number" | "text" | "select" | "textarea" | "checks";
export type Field = {
  name: string; label: string; type: FieldType; def?: string; options?: string[]; hint?: string; optional?: boolean; rows?: number;
};
export type Tool = {
  id: string; group: "Trader" | "Investor"; title: string; blurb: string;
  method: "POST" | "GET"; path: string; demoData?: boolean; fields: Field[];
  build: (v: Record<string, string>) => unknown | null; // null for GET
  pathFor?: (v: Record<string, string>) => string;
  view?: "payoff" | "backtest" | "screener" | "portrisk" | "fundscreen";
};

const num = (s: string) => (s.trim() === "" ? undefined : Number(s));
const lines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);
const csvRows = (s: string) => lines(s).map((l) => l.split(/[,\t]/).map((x) => x.trim()));
const kv = (s: string) => Object.fromEntries(lines(s).map((l) => { const [k, v] = l.split(/[=:]/); return [k.trim(), Number(v)]; }));

const HOLDINGS = "symbol,qty,avg_price\nTCS,10,3400\nINFY,25,1500\nITC,100,410\nHDFCBANK,20,1600";

export const TOOLS: Tool[] = [
  {
    id: "size", group: "Trader", title: "Position size", method: "POST", path: "/tools/position-size",
    blurb: "How many shares so a stop-out costs only what you decided to risk. Leave stop empty to place one outside normal daily noise.",
    fields: [
      { name: "entry", label: "Entry price", type: "number", def: "500" },
      { name: "stop", label: "Stop price", type: "number", def: "", optional: true, hint: "blank = use volatility" },
      { name: "vol", label: "Daily volatility %", type: "number", def: "1.6", optional: true, hint: "used only if stop is blank" },
      { name: "capital", label: "Capital", type: "number", def: "500000" },
      { name: "risk_pct", label: "Risk per trade %", type: "number", def: "1" },
      { name: "side", label: "Side", type: "select", options: ["long", "short"], def: "long" },
      { name: "lot", label: "Lot size", type: "number", def: "1" },
    ],
    build: (v) => ({ entry: num(v.entry), stop: num(v.stop), daily_vol_pct: num(v.vol), capital: num(v.capital), risk_pct: num(v.risk_pct), side: v.side, lot_size: num(v.lot) }),
  },
  {
    id: "costs", group: "Trader", title: "Trade costs", method: "POST", path: "/tools/costs",
    blurb: "Every charge on a round trip, and how far price must move before you are even.",
    fields: [
      { name: "segment", label: "Segment", type: "select", options: ["equity_delivery", "equity_intraday", "futures", "options"], def: "equity_intraday" },
      { name: "buy", label: "Buy price", type: "number", def: "500" },
      { name: "sell", label: "Sell price", type: "number", def: "505" },
      { name: "qty", label: "Quantity", type: "number", def: "200" },
    ],
    build: (v) => ({ segment: v.segment, buy_price: num(v.buy), sell_price: num(v.sell), qty: num(v.qty) }),
  },
  {
    id: "journal", group: "Trader", title: "Trade journal", method: "POST", path: "/tools/journal",
    blurb: "Paste your broker tradebook CSV. Win rate, expectancy, drawdown, best and worst hours, revenge-trade and over-sizing flags.",
    fields: [
      { name: "csv", label: "Tradebook CSV", type: "textarea", rows: 8, def: "symbol,trade_date,order_execution_time,trade_type,quantity,price\nABC,2026-01-05,2026-01-05T09:20:00,buy,10,100\nABC,2026-01-05,2026-01-05T10:20:00,sell,10,110\nXYZ,2026-01-06,2026-01-06T09:30:00,buy,10,200\nXYZ,2026-01-06,2026-01-06T09:50:00,sell,10,190\nXYZ,2026-01-06,2026-01-06T10:05:00,buy,30,188\nXYZ,2026-01-06,2026-01-06T10:40:00,sell,30,180" },
      { name: "cost", label: "Cost per trade", type: "number", def: "0" },
    ],
    build: (v) => ({ csv: v.csv, cost_per_trade: num(v.cost) ?? 0 }),
  },
  {
    id: "opt", group: "Trader", title: "Option price and Greeks", method: "POST", path: "/tools/options/analyse",
    blurb: "Black-Scholes price and Greeks. Enter the market premium to back out implied volatility, and compare it to what the stock actually moves.",
    fields: [
      { name: "spot", label: "Spot", type: "number", def: "24000" },
      { name: "strike", label: "Strike", type: "number", def: "24200" },
      { name: "days", label: "Days to expiry", type: "number", def: "7" },
      { name: "kind", label: "Type", type: "select", options: ["call", "put"], def: "call" },
      { name: "price", label: "Market premium", type: "number", def: "95", optional: true },
      { name: "vol", label: "Volatility % (if no premium)", type: "number", def: "", optional: true },
      { name: "exp", label: "Expected daily move %", type: "number", def: "0.8", optional: true },
    ],
    build: (v) => ({ spot: num(v.spot), strike: num(v.strike), days: num(v.days), kind: v.kind, market_price: num(v.price), vol_pct: num(v.vol), expected_daily_vol_pct: num(v.exp) }),
  },
  {
    id: "payoff", group: "Trader", title: "Payoff builder", method: "POST", path: "/tools/options/payoff", view: "payoff",
    blurb: "One leg per line: type, strike, premium, quantity (negative = sold). Shows profit and loss at expiry and break-evens. Margin for sold options is not estimated: use your broker's SPAN calculator.",
    fields: [
      { name: "legs", label: "Legs", type: "textarea", rows: 5, def: "call,24000,210,-1\ncall,24300,95,1\nput,23700,90,-1\nput,23400,40,1" },
      { name: "lo", label: "Chart from", type: "number", def: "23000" },
      { name: "hi", label: "Chart to", type: "number", def: "24700" },
    ],
    build: (v) => ({ legs: csvRows(v.legs).map(([kind, strike, premium, qty]) => ({ kind, strike: +strike, premium: +premium, qty: +qty })), lo: num(v.lo), hi: num(v.hi) }),
  },
  {
    id: "chain", group: "Trader", title: "Open interest and max pain", method: "POST", path: "/tools/options/chain",
    blurb: "Paste strike, call OI, put OI per line from the option chain.",
    fields: [{ name: "rows", label: "strike, call OI, put OI", type: "textarea", rows: 6, def: "23800,120000,410000\n24000,310000,520000\n24200,560000,300000\n24400,610000,140000" }],
    build: (v) => csvRows(v.rows).map(([strike, c, p]) => ({ strike: +strike, call_oi: +c, put_oi: +p })),
  },
  {
    id: "day", group: "Trader", title: "Daily loss limit", method: "POST", path: "/tools/risk/day",
    blurb: "Enter today's realised P&L per closed trade, in order. The limit is a rule you set before the day starts.",
    fields: [
      { name: "pnls", label: "Trade P&L, comma separated", type: "text", def: "-400, 250, -600, -300" },
      { name: "max", label: "Max loss today", type: "number", def: "2000" },
      { name: "trades", label: "Max trades", type: "number", def: "", optional: true },
    ],
    build: (v) => ({ pnls: v.pnls.split(",").map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x)), max_loss: num(v.max), max_trades: num(v.trades) }),
  },
  {
    id: "check", group: "Trader", title: "Pre-trade checklist", method: "POST", path: "/tools/risk/checklist",
    blurb: "Tick every line that is true. Required lines block the trade until they are.",
    fields: [{ name: "answers", label: "Before you click buy", type: "checks" }],
    build: (v) => JSON.parse(v.answers || "{}"),
  },
  {
    id: "expiry", group: "Trader", title: "Expiry dates", method: "POST", path: "/tools/calendar/expiries",
    blurb: "NSE derivatives expire on Tuesdays and BSE on Thursdays. Add exchange holidays yourself.",
    fields: [
      { name: "year", label: "Year", type: "number", def: "2026" },
      { name: "month", label: "Month (1-12)", type: "number", def: "11" },
      { name: "ex", label: "Exchange", type: "select", options: ["NSE", "BSE"], def: "NSE" },
      { name: "hol", label: "Holidays (YYYY-MM-DD, one per line)", type: "textarea", rows: 2, def: "", optional: true },
    ],
    build: (v) => ({ year: num(v.year), month: num(v.month), exchange: v.ex, holidays: lines(v.hol) }),
  },
  {
    id: "screen", group: "Trader", title: "Screener", method: "GET", path: "/market/screener", demoData: true, view: "screener",
    blurb: "Rank a universe by momentum, volatility, 52-week position and volume spikes. Uses your local NSE data when loaded; otherwise placeholder prices, clearly labelled.",
    fields: [], build: () => null,
  },
  {
    id: "bt", group: "Trader", title: "Backtester", method: "GET", path: "/market/backtest", demoData: true, view: "backtest",
    blurb: "Moving-average crossover with Indian-style costs and slippage, then walk-forward out-of-sample results and a worst-case drawdown simulation. The out-of-sample line is the one to believe.",
    fields: [
      { name: "ticker", label: "Ticker", type: "text", def: "TCS" },
      { name: "cost", label: "Cost, bps per trade", type: "number", def: "10" },
      { name: "slip", label: "Slippage, bps", type: "number", def: "5" },
    ],
    pathFor: (v) => `/market/backtest/${encodeURIComponent(v.ticker.trim() || "TCS")}?cost_bps=${v.cost || 10}&slippage_bps=${v.slip || 5}`,
    build: () => null,
  },
  {
    id: "alloc", group: "Investor", title: "Portfolio allocation", method: "POST", path: "/tools/portfolio/allocation",
    blurb: "Value, weights and concentration. Prices are typed in until a feed is connected.",
    fields: [
      { name: "csv", label: "Holdings CSV", type: "textarea", rows: 5, def: HOLDINGS },
      { name: "prices", label: "Current prices, SYMBOL=price per line", type: "textarea", rows: 5, def: "TCS=3550\nINFY=1620\nITC=470\nHDFCBANK=1710" },
    ],
    build: (v) => ({ csv: v.csv, prices: kv(v.prices) }),
  },
  {
    id: "risk", group: "Investor", title: "Portfolio risk", method: "POST", path: "/market/portfolio-risk", demoData: true, view: "portrisk",
    blurb: "Likely one-week and one-month loss range, correlation, and a 2020-style and 2008-style crash. Uses your local NSE data when loaded; otherwise placeholder prices, clearly labelled.",
    fields: [{ name: "csv", label: "Holdings CSV", type: "textarea", rows: 5, def: HOLDINGS }],
    build: (v) => ({ csv: v.csv }),
  },
  {
    id: "xirr", group: "Investor", title: "Your real return (XIRR)", method: "POST", path: "/tools/portfolio/xirr",
    blurb: "Money you put in as negative amounts, money out and today's value as positive. One per line: date, amount.",
    fields: [{ name: "flows", label: "date, amount", type: "textarea", rows: 5, def: "2024-01-15,-100000\n2024-08-01,-50000\n2025-06-10,-50000\n2026-11-01,238000" }],
    build: (v) => csvRows(v.flows).map(([date, amount]) => ({ date, amount: +amount })),
  },
  {
    id: "sip", group: "Investor", title: "SIP calculator", method: "POST", path: "/tools/planner/sip",
    blurb: "What a monthly investment could become at an assumed return. The return is your assumption, not a promise.",
    fields: [
      { name: "m", label: "Monthly amount", type: "number", def: "15000" },
      { name: "r", label: "Assumed return % a year", type: "number", def: "11" },
      { name: "y", label: "Years", type: "number", def: "15" },
      { name: "s", label: "Yearly step-up %", type: "number", def: "8" },
    ],
    build: (v) => ({ monthly: num(v.m), annual_return_pct: num(v.r), years: num(v.y), step_up_pct: num(v.s) }),
  },
  {
    id: "goal", group: "Investor", title: "Goal planner", method: "POST", path: "/tools/planner/goal",
    blurb: "The monthly SIP needed for a goal stated in today's rupees, after inflation.",
    fields: [
      { name: "g", label: "Goal in today's rupees", type: "number", def: "10000000" },
      { name: "y", label: "Years", type: "number", def: "18" },
      { name: "r", label: "Assumed return %", type: "number", def: "11" },
      { name: "i", label: "Inflation %", type: "number", def: "6" },
    ],
    build: (v) => ({ goal_today: num(v.g), years: num(v.y), annual_return_pct: num(v.r), inflation_pct: num(v.i) }),
  },
  {
    id: "rebal", group: "Investor", title: "Rebalancing", method: "POST", path: "/tools/planner/rebalance",
    blurb: "One line per asset: name, current value, target %. It only asks you to trade when drift passes the band.",
    fields: [
      { name: "rows", label: "name, value, target %", type: "textarea", rows: 4, def: "Equity,720000,60\nDebt,230000,30\nGold,50000,10" },
      { name: "cash", label: "New money to add", type: "number", def: "0" },
    ],
    build: (v) => { const r = csvRows(v.rows); return { values: Object.fromEntries(r.map(([n, val]) => [n, +val])), targets: Object.fromEntries(r.map(([n, , t]) => [n, +t / 100])), new_cash: num(v.cash) ?? 0 }; },
  },
  {
    id: "fscreen", group: "Investor", title: "Fundamentals screener", method: "POST", path: "/tools/screener/fundamentals", view: "fundscreen",
    blurb: "IntelliStock has no fundamentals feed, so bring your own: export a screen from Screener.in (or any CSV with a name column and columns like P/E, ROE, ROCE, Debt / Eq) and paste it. Filters use your numbers exactly. Stocks missing a number you filter on are left out and counted.",
    fields: [
      { name: "csv", label: "Your fundamentals CSV", type: "textarea", rows: 8, def: `Name,P/E,ROE %,ROCE %,Debt / Eq,Prom. Hold. %,Profit Var 3Yrs %,Mar Cap Rs.Cr.
SAMPLE-A (made up),12.5,18,22,0.1,60,15,5000
SAMPLE-B (made up),45,6,8,1.8,30,-2,900
SAMPLE-C (made up),22,25,30,0.0,70,40,100` },
      { name: "roe_min", label: "ROE at least %", type: "number", def: "15", optional: true },
      { name: "roce_min", label: "ROCE at least %", type: "number", def: "", optional: true },
      { name: "pe_max", label: "P/E at most", type: "number", def: "", optional: true },
      { name: "de_max", label: "Debt / equity at most", type: "number", def: "0.5", optional: true },
      { name: "prom_min", label: "Promoter holding at least %", type: "number", def: "", optional: true },
      { name: "growth_min", label: "3-year profit growth at least %", type: "number", def: "", optional: true },
      { name: "sort", label: "Sort by", type: "select", options: ["quality", "roe", "roce", "pe", "debt_equity", "promoter_holding", "profit_cagr_3y", "market_cap_cr"], def: "quality" },
    ],
    build: (v) => {
      const f: { field: string; min?: number; max?: number }[] = [];
      const add = (field: string, key: string, kind: "min" | "max") => { const n = num(v[key]); if (n !== undefined && Number.isFinite(n)) f.push({ field, [kind]: n }); };
      add("roe", "roe_min", "min"); add("roce", "roce_min", "min"); add("pe", "pe_max", "max");
      add("debt_equity", "de_max", "max"); add("promoter_holding", "prom_min", "min"); add("profit_cagr_3y", "growth_min", "min");
      return { csv: v.csv, filters: f, sort: v.sort, limit: 100 };
    },
  },
  {
    id: "fund", group: "Investor", title: "Quality score", method: "POST", path: "/tools/fundamentals/score",
    blurb: "Scores the numbers you enter. Missing inputs are left out, not guessed. Typical keys: roe, roce, debt_equity, interest_cover, sales_growth_5y, profit_growth_5y, promoter_pledge.",
    fields: [{ name: "kv", label: "key=value per line", type: "textarea", rows: 6, def: "roe=21\nroce=26\ndebt_equity=0.2\nsales_growth_5y=14\nprofit_growth_5y=16" }],
    build: (v) => kv(v.kv),
  },
  {
    id: "ann", group: "Investor", title: "Announcement digest", method: "POST", path: "/tools/announcements/digest",
    blurb: "Paste exchange filings, one per line: symbol, YYYY-MM-DD, headline. A keyword classifier sorts what matters. It does not read the filing for you.",
    fields: [{ name: "rows", label: "symbol, date, headline", type: "textarea", rows: 5, def: "TCS,2026-11-01,Board approves interim dividend of Rs 10 per share\nITC,2026-11-01,Intimation of analyst meet\nWIPRO,2026-10-31,Resignation of Chief Financial Officer" }],
    build: (v) => csvRows(v.rows).map(([symbol, date, ...t]) => ({ symbol, date, title: t.join(", ") })),
  },
  {
    id: "tax", group: "Investor", title: "Capital gains estimate", method: "POST", path: "/tools/tax/capital-gains",
    blurb: "Listed-equity delivery trades only. One fill per line: symbol, date, buy/sell, qty, price. An estimate: have a chartered accountant confirm before filing.",
    fields: [{ name: "rows", label: "symbol, date, side, qty, price", type: "textarea", rows: 6, def: "TCS,2025-01-10,buy,10,3300\nTCS,2026-03-05,sell,6,3700\nINFY,2026-02-01,buy,20,1500\nINFY,2026-09-20,sell,20,1650" }],
    build: (v) => csvRows(v.rows).map(([symbol, date, side, qty, price]) => ({ symbol, date, side, qty: +qty, price: +price })),
  },
];
