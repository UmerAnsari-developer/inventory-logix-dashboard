# DATA_GENERATION_REPORT.md

## Dataset Summary
- Total rows: 54,507
- Total SKUs: 65
- Total warehouses: 10
- Total suppliers: 36
- Date range: 2024-01-01 -> 2026-10-02

## Demand Statistics
- Stockout days: 1,649
- Controlled anomalies: {'spike': 688, 'drop': 482, 'unusual_quantity': 239}

## Forecast Suitability
- SKUs suitable for ARIMA: 52
- SKUs suitable for SARIMA: 0
- Intermittent SKUs (zero% > 50): 13
- Insufficient-data SKUs: 0
- SKUs with 300+ observations: 52
- SKUs with 500+ observations: 52

## Per-SKU Statistics

| SKU | Group | Days | Active | Zero% | Avg | Median | Std | CV | Weekly ACF | Trend% |
|-----|-------|------|--------|-------|-----|--------|-----|-----|-----------|--------|
| SKU-SYN-1000 | A_stable | 1006 | 905 | 10.0 | 14.2 | 14 | 12.26 | 0.86 | -0.043 | -2.4 |
| SKU-SYN-1001 | A_stable | 1006 | 905 | 10.0 | 13.08 | 13 | 9.92 | 0.76 | 0.005 | 3.0 |
| SKU-SYN-1002 | A_stable | 1006 | 903 | 10.2 | 13.1 | 13 | 10.04 | 0.77 | -0.037 | 1.0 |
| SKU-SYN-1003 | A_stable | 1006 | 908 | 9.7 | 11.18 | 11 | 9.97 | 0.89 | 0.008 | 8.6 |
| SKU-SYN-1004 | A_stable | 1006 | 907 | 9.8 | 9.41 | 9 | 6.83 | 0.73 | -0.051 | 4.7 |
| SKU-SYN-1005 | A_stable | 1006 | 909 | 9.6 | 10.53 | 10 | 8.08 | 0.77 | -0.019 | 8.8 |
| SKU-SYN-1006 | A_stable | 1006 | 907 | 9.8 | 13.31 | 13 | 10.85 | 0.82 | -0.024 | 1.0 |
| SKU-SYN-1007 | A_stable | 1006 | 899 | 10.6 | 11.28 | 11 | 9.77 | 0.87 | 0.056 | 15.5 |
| SKU-SYN-1008 | A_stable | 1006 | 911 | 9.4 | 9.05 | 8 | 9.27 | 1.02 | 0.097 | -3.7 |
| SKU-SYN-1009 | A_stable | 1006 | 911 | 9.4 | 11.92 | 12 | 7.16 | 0.6 | 0.061 | 2.6 |
| SKU-SYN-1010 | A_stable | 1006 | 899 | 10.6 | 12.51 | 12 | 10.93 | 0.87 | 0.038 | 6.9 |
| SKU-SYN-1011 | A_stable | 1006 | 912 | 9.3 | 9.8 | 9 | 8.47 | 0.86 | -0.004 | -4.5 |
| SKU-SYN-1012 | A_stable | 1006 | 910 | 9.5 | 8.65 | 9 | 6.59 | 0.76 | 0.001 | -6.5 |
| SKU-SYN-1013 | A_stable | 1006 | 898 | 10.7 | 13.8 | 14 | 10.33 | 0.75 | 0.007 | -3.8 |
| SKU-SYN-1014 | A_stable | 1006 | 902 | 10.3 | 10.91 | 11 | 9.05 | 0.83 | 0.004 | 6.9 |
| SKU-SYN-1015 | A_stable | 1006 | 883 | 12.2 | 8.79 | 9 | 7.55 | 0.86 | 0.01 | 9.3 |
| SKU-SYN-1016 | A_stable | 1006 | 892 | 11.3 | 13.25 | 13 | 10.45 | 0.79 | -0.016 | 17.4 |
| SKU-SYN-1017 | A_stable | 1006 | 919 | 8.6 | 11.83 | 12 | 7.9 | 0.67 | -0.017 | -0.6 |
| SKU-SYN-1018 | B_trending | 1006 | 861 | 14.4 | 7.88 | 8 | 7.83 | 0.99 | 0.008 | -40.2 |
| SKU-SYN-1019 | B_trending | 1006 | 841 | 16.4 | 7.91 | 7 | 7.48 | 0.95 | 0.077 | -48.3 |
| SKU-SYN-1020 | B_trending | 1006 | 870 | 13.5 | 10.86 | 11 | 8.22 | 0.76 | -0.011 | 11.3 |
| SKU-SYN-1021 | B_trending | 1006 | 842 | 16.3 | 7.26 | 7 | 5.57 | 0.77 | -0.057 | -18.0 |
| SKU-SYN-1022 | B_trending | 1006 | 857 | 14.8 | 12.75 | 13 | 10.11 | 0.79 | 0.019 | 28.6 |
| SKU-SYN-1023 | B_trending | 1006 | 868 | 13.7 | 11.47 | 11 | 10.68 | 0.93 | 0.007 | 16.7 |
| SKU-SYN-1024 | B_trending | 1006 | 867 | 13.8 | 10.02 | 9 | 9.45 | 0.94 | 0.0 | 21.5 |
| SKU-SYN-1025 | B_trending | 1006 | 871 | 13.4 | 8.82 | 9 | 7.24 | 0.82 | 0.013 | -26.7 |
| SKU-SYN-1026 | B_trending | 1006 | 852 | 15.3 | 10.9 | 11 | 8.82 | 0.81 | -0.024 | 26.8 |
| SKU-SYN-1027 | B_trending | 1006 | 862 | 14.3 | 12.76 | 13 | 11.39 | 0.89 | -0.022 | 34.0 |
| SKU-SYN-1028 | C_seasonal | 1006 | 847 | 15.8 | 16.04 | 17 | 12.66 | 0.79 | 0.006 | -4.6 |
| SKU-SYN-1029 | C_seasonal | 1006 | 869 | 13.6 | 15.8 | 16 | 12.5 | 0.79 | 0.029 | 4.4 |
| SKU-SYN-1030 | C_seasonal | 1006 | 855 | 15.0 | 16.66 | 17 | 13.73 | 0.82 | 0.017 | 4.6 |
| SKU-SYN-1031 | C_seasonal | 1006 | 862 | 14.3 | 12.38 | 12 | 12.55 | 1.01 | -0.005 | -1.3 |
| SKU-SYN-1032 | C_seasonal | 1006 | 870 | 13.5 | 11.75 | 12 | 9.67 | 0.82 | 0.054 | -3.5 |
| SKU-SYN-1033 | C_seasonal | 1006 | 850 | 15.5 | 13.51 | 14 | 12.43 | 0.92 | 0.03 | -6.9 |
| SKU-SYN-1034 | C_seasonal | 1006 | 831 | 17.4 | 9.27 | 10 | 7.57 | 0.82 | -0.007 | -15.9 |
| SKU-SYN-1035 | C_seasonal | 1006 | 857 | 14.8 | 18.45 | 19 | 14.32 | 0.78 | 0.024 | -2.1 |
| SKU-SYN-1036 | C_seasonal | 1006 | 872 | 13.3 | 15.4 | 15 | 12.99 | 0.84 | 0.035 | -4.0 |
| SKU-SYN-1037 | C_seasonal | 1006 | 851 | 15.4 | 16.88 | 17 | 17.65 | 1.05 | -0.021 | 14.5 |
| SKU-SYN-1038 | C_seasonal | 1006 | 845 | 16.0 | 16.38 | 17 | 11.71 | 0.71 | 0.041 | -6.1 |
| SKU-SYN-1039 | C_seasonal | 1006 | 844 | 16.1 | 17.04 | 17 | 17.2 | 1.01 | -0.069 | 15.6 |
| SKU-SYN-1040 | C_seasonal | 1006 | 864 | 14.1 | 11.78 | 11 | 11.16 | 0.95 | 0.009 | -7.6 |
| SKU-SYN-1041 | C_seasonal | 1006 | 838 | 16.7 | 16.6 | 17 | 15.62 | 0.94 | -0.018 | -5.9 |
| SKU-SYN-1042 | D_intermittent | 1006 | 161 | 84.0 | 1.96 | 0 | 5.83 | 2.97 | 0.002 | 6.7 |
| SKU-SYN-1043 | D_intermittent | 1006 | 192 | 80.9 | 1.54 | 0 | 5.26 | 3.41 | -0.016 | -7.0 |
| SKU-SYN-1044 | D_intermittent | 1006 | 173 | 82.8 | 1.33 | 0 | 4.03 | 3.04 | -0.016 | -5.4 |
| SKU-SYN-1045 | D_intermittent | 1006 | 170 | 83.1 | 2.35 | 0 | 7.01 | 2.98 | -0.013 | -38.0 |
| SKU-SYN-1046 | D_intermittent | 1006 | 182 | 81.9 | 1.32 | 0 | 3.47 | 2.63 | -0.022 | 8.2 |
| SKU-SYN-1047 | D_intermittent | 1006 | 161 | 84.0 | 3.11 | 0 | 8.2 | 2.63 | -0.01 | 1.0 |
| SKU-SYN-1048 | D_intermittent | 1006 | 167 | 83.4 | 3.13 | 0 | 9.72 | 3.11 | -0.022 | 65.7 |
| SKU-SYN-1049 | D_intermittent | 1006 | 169 | 83.2 | 3.22 | 0 | 10.36 | 3.21 | -0.014 | -35.1 |
| SKU-SYN-1050 | D_intermittent | 1006 | 172 | 82.9 | 1.98 | 0 | 4.72 | 2.38 | -0.01 | -4.2 |
| SKU-SYN-1051 | D_intermittent | 1006 | 190 | 81.1 | 1.6 | 0 | 4.13 | 2.57 | -0.031 | 5.5 |
| SKU-SYN-1052 | D_intermittent | 1006 | 187 | 81.4 | 1.77 | 0 | 4.5 | 2.55 | -0.003 | 14.4 |
| SKU-SYN-1053 | D_intermittent | 1006 | 181 | 82.0 | 2.13 | 0 | 5.36 | 2.51 | -0.021 | -6.3 |
| SKU-SYN-1054 | D_intermittent | 1006 | 154 | 84.7 | 2.72 | 0 | 8.04 | 2.95 | 0.031 | -4.2 |
| SKU-SYN-1055 | E_promotional | 1006 | 811 | 19.4 | 9.31 | 10 | 7.7 | 0.83 | 0.002 | 11.7 |
| SKU-SYN-1056 | E_promotional | 1006 | 789 | 21.6 | 11.71 | 12 | 12.22 | 1.04 | -0.014 | -13.6 |
| SKU-SYN-1057 | E_promotional | 1006 | 802 | 20.3 | 12.08 | 12 | 12.9 | 1.07 | 0.009 | -0.2 |
| SKU-SYN-1058 | E_promotional | 1006 | 804 | 20.1 | 8.97 | 9 | 8.85 | 0.99 | -0.024 | -3.3 |
| SKU-SYN-1059 | E_promotional | 1006 | 801 | 20.4 | 9.68 | 10 | 10.75 | 1.11 | -0.021 | -14.6 |
| SKU-SYN-1060 | E_promotional | 1006 | 811 | 19.4 | 8.38 | 9 | 6.09 | 0.73 | 0.024 | 1.2 |
| SKU-SYN-1061 | E_promotional | 1006 | 818 | 18.7 | 11.57 | 12 | 11.47 | 0.99 | -0.04 | 0.9 |
| SKU-SYN-1062 | E_promotional | 1006 | 802 | 20.3 | 12.8 | 14 | 11.8 | 0.92 | -0.012 | -3.1 |
| SKU-SYN-1063 | E_promotional | 1006 | 804 | 20.1 | 12.01 | 12 | 10.98 | 0.91 | -0.021 | -6.3 |
| SKU-SYN-1064 | E_promotional | 1006 | 826 | 17.9 | 11.75 | 12 | 10.32 | 0.88 | -0.036 | 0.2 |

## Data-Quality Checks

- No integrity issues: all SKUs known, quantities > 0, types valid, dates in range

## Schema Mapping (spec §28) — Fields NOT Supported by Existing Schema

The following DataCo-like fields have no counterpart in the InventoryLogix
schema and are preserved in CSVs only (not silently added to the schema):

- `movements`: transaction_id/order_id/order_item_id (encoded in `reference`),
  shipping_date, discount, sales_amount, cost_amount, profit_amount,
  customer_segment, order_status, shipping_mode, delivery_days,
  late_delivery_flag, stockout_flag, fulfilled_quantity
  (stockout censoring: DB stores fulfilled quantity only — requested-vs-fulfilled
  distinction is NOT representable; full detail in transactions.csv)
- `products`: subcategory, department, warehouse_id FK (single `warehouse` VARCHAR)
- `suppliers`: supplier_region (held in `location`), min_order_quantity
- `warehouses`: city/state/region (held in `location`), capacity

- Dataset identifier: `synthetic_dataco_2024_current` (movements.reference prefix `SYN-`)
