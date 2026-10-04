# Sector lists

A custom sector is a JSON file here with the tickers you want screened together:

```json
{
  "label": "My chip makers",
  "tickers": ["NVDA", "AMD", "INTC", "TXN", "ADI", "MU", "QCOM"]
}
```

Save it as `sectors/{name}.json` (letters, digits, `_` and `-`), then screen it from the site's
Run pipeline tab (Sector → My list → `{name}`) or with

```
python pipeline.py sector list:{name}
gh workflow run pipeline.yml -f sector=list:{name}
```

The other sector kinds need no file:

| Kind | Example | Members |
|---|---|---|
| `sic:` | `sic:3674` | every filer under that SEC industry code that has recent data |
| `sic-of:` | `sic-of:AAPL` | the industry code that company files under |
| `traits:` | `traits:stage=high growth;asset_intensity=light` | companies across all industries whose traits match (largest 100) |
| `list:` | `list:example_chips` | the tickers in this folder's file |

Trait values: stage = high growth, mature grower, mature, declining · predictability = high, medium,
low · asset_intensity = light, moderate, heavy · capital_structure = low leverage, moderate
leverage, high leverage, financial.
