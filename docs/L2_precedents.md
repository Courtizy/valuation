# L2 Precedent Transactions (transaction comps)

*Status: built. `L2_models/precedents`, with the deal-list reader and per-deal math in `_core/deals.py`. Inputs: `company_detail.json`, `configs/public/assumptions/{TICKER}/precedents.json` (on the site, the deal list uploaded on the device) and `deal.json` (pre-announcement price).*

## Deal list

A CSV file, or a tab-separated paste copied straight from Excel, one deal per row with a header row. Headers are matched loosely, so an SDC Platinum export works as is:

| Field | Headers it matches (start of the header) |
|---|---|
| target (required) | Target Name, Target |
| offer price (required) | Price Per Share, Offer Price |
| price 1 week before | Target Share Price 1 Week Prior…, Price 1 Week, Pre-announcement Price |
| price 4 weeks before | Target Share Price 4 Weeks Prior…, Price 4 Weeks |
| shares, net debt | Shares Out., Shares Outstanding; Net Debt |
| sales, EBITDA | Target Net Sales LTM, Sales, Revenue; Target EBITDA LTM, EBITDA |
| EV at the offer price | Enterprise Value evaluated at offer price, Transaction EV, Enterprise Value |
| also read | Acquiror Name, Year Announced, Date Announced, Target Primary SIC, Target Nation, Premium, Best |

Figures in a row share one unit (SDC: $ millions); only ratios carry over to the target. Template: `configs/public/assumptions/_template/precedents.json`.

## Per deal

    premium            = max(offer / price 1 week before − 1, offer / price 4 weeks before − 1);
                         negative → 10%, above 100% → 100% (the course's "best premium paid")
    transaction EV     = the source's EV at the offer price, else offer × shares + net debt
    pre-announcement EV = price 1 week before × shares + net debt
    multiples          = EV / sales and EV / EBITDA (positive only)

Target implied value per share: (multiple × target metric − target net debt) / target shares; from a premium, pre-announcement price × (1 + premium).

## Best deals (course Best_TC_Comps)

The deals ticked as most comparable (a "Best" column, the site's checkboxes, or the first five). Each deal's EV is rebuilt from offer × shares + net debt. Range = lowest / average / highest implied value.

## All deals (course Cent_Tend_TC)

Mean, minimum, quartiles and maximum of premium, transaction and pre-announcement EV/Sales and EV/EBITDA, and EBITDA margin. Premium paid at the 1st quartile / median / 3rd quartile. Multiples at a percentile ±10 points; the percentile is where the target's own pre-announcement multiple ranks among the deals' (Excel PERCENTRANK.EXC), else the median, or set it in `central.percentile`.

## Into the deal summary

`choice` follows the course switch: 0 (default) = standalone rows (pre-announcement EV/Sales, EV/EBITDA) from best deals and offer rows (transaction EV/Sales, EV/EBITDA, premium paid) from all deals; 1 = best deals only; 2 = all deals only. Default weights: 10% + 10% standalone, 2% + 2% + 30% offer.

## Parity (local workbooks)

`tests/test_course_parity.py`: Cent_Tend_TC's statistics table, percentiles and implied ranges from the workbook's Orig_TC_Data, and Best_TC_Comps' per-deal implied values and averages. Passing on the TSYS, SNN and Tower workbooks.

## Not yet

The premium regression on deal traits (recent deal, same industry, cash, tender offer) from the Regression sheet, and pulling deals from SEC merger filings.
