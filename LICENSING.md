# Data licensing: read this before you show anyone prices

This is a summary of what NSE's own pages say, not legal advice. I read NSE's data policy page and its
end-of-day data tariff through a page summariser on 2026-11-02, and could not read NSE's separate Terms of
Use and Copyright pages. Confirm everything with NSE Data & Analytics before you rely on it.

## What NSE says

- NSE's data policy defines market data to include **end-of-day data, historical data and corporate data**.
  Commercial use needs a "Relevant Agreement" with **NSE Data & Analytics Limited** (NSE's data subsidiary),
  and redistribution is not allowed except as that agreement permits.
  Source: https://www.nseindia.com/market-data/nse-data-policy
- NSE's end-of-day data tariff (dated 24 Apr 2026) lists **Capital Market end-of-day display at INR 1,00,000 per
  medium (domestic)**, and says a website and a mobile app count as two different mediums charged separately.
  Written consent from NSE Data & Analytics is mandatory where EOD data is provided to a vendor's clients.
  Source: https://nsearchives.nseindia.com//web/mediaattachment/2026-04/Download_End_of_the_Day_Data_Tariff_20260424120810.pdf
- Not answered by what I could read: whether the free daily files on NSE's website may be reused for
  personal research. That is why this project treats them as personal-use only.

## What the code enforces

| Setting | Meaning | Production behaviour |
| --- | --- | --- |
| `DATA_PROVIDER=nse` | Files you downloaded from NSE with `scripts/fetch_data.py` | Refused with 503 unless `NSE_DATA_LICENSED=true` |
| `DATA_PROVIDER=local` | Licensed vendor data loaded with `scripts/import_vendor_csv.py --adjusted` | Allowed: the licence is between you and the vendor |
| `DATA_PROVIDER=synthetic` or a `FIXTURE` store | Placeholders and test fixtures | Always refused in production |

`NSE_DATA_LICENSED=true` is a statement that you hold an agreement. Do not set it otherwise.

## Realistic routes to a product

1. **Do not redistribute prices.** Let each user bring their own data (their broker's export, their own
   download) and run the calculators on it. Your product is the analysis, not the data. This avoids the
   redistribution question for the tools that need no market data: position size, costs, journal,
   payoff, checklist, SIP, goals, rebalancing, tax.
2. **Buy a licence.** NSE Data & Analytics sells it directly (see the tariff above), and data vendors resell
   licensed feeds. Costs and terms change, so ask for a current quote.
3. **Broker APIs.** Several brokers offer historical-data APIs to their own customers. Their terms on reuse
   inside a product vary and I have not verified any of them.

Showing derived analysis (a risk range) is different in law from redistributing the prices themselves, but
where that line sits is a question for NSE Data & Analytics or a lawyer, not for this file.
