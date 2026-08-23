# K 值 refinement

只在 best single / best blend 上改 K。选参仍只看 IS。

| id | family | logic | week_turn | skipped_buy | n_is_sharpe | n_is_ret | n_is_mdd | n_oos_sharpe | n_oos_ret | n_val_sharpe | n_val_ret | base | k |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| f11_mom3_high5_k3 | refine | f11_mom3_high5 Top3 | 0.978 | 177 | 0.323 | 69.091 | 50.211 | -0.072 | -6.496 | 0.008 | 0.244 | f11_mom3_high5 | 3 |
| f11_mom3_high5_k5 | refine | f11_mom3_high5 Top5 | 0.981 | 277 | 0.392 | 72.217 | 44.841 | 0.377 | 32.136 | -0.043 | -1.015 | f11_mom3_high5 | 5 |
| f11_mom3_high5_k8 | refine | f11_mom3_high5 Top8 | 0.978 | 437 | 0.361 | 55.313 | 35.922 | -0.152 | -9.971 | 2.26 | 39.309 | f11_mom3_high5 | 8 |
| blend_icir_k3 | refine | blend_icir Top3 | 0.976 | 11 | -0.686 | -58.31 | 71.958 | -0.414 | -23.493 | 0.284 | 6.034 | blend_icir | 3 |
| blend_icir_k5 | refine | blend_icir Top5 | 0.965 | 16 | -0.315 | -28.745 | 48.104 | -0.593 | -29.692 | -0.462 | -8.623 | blend_icir | 5 |
| blend_icir_k8 | refine | blend_icir Top8 | 0.955 | 22 | -0.537 | -41.812 | 55.286 | -0.445 | -21.916 | -0.385 | -6.402 | blend_icir | 8 |
