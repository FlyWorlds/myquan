# 去冗余组合

相关性阈值 0.7；权重只用 IS。保留腿：['f9_e5_20', 'f10_near5', 'f3_rev20', 'f10_persist20']

| id | family | logic | ic_is | week_turn | skipped_buy | n_is_sharpe | n_is_ret | n_is_mdd | n_oos_sharpe | n_oos_ret | n_val_sharpe | n_val_ret | legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| blend_equal | blend | 去冗余后截面 z 等权 Top5：f9_e5_20+f10_near5+f3_rev20+f10_persist20 | 0.002 | 0.957 | 14 | -0.472 | -38.71 | 52.392 | -0.094 | -4.342 | 0.661 | 8.585 | f9_e5_20,f10_near5,f3_rev20,f10_persist20 |
| blend_icir | blend | 去冗余后 IS-ICIR 加权 Top5：f9_e5_20+f10_near5+f3_rev20+f10_persist20 | 0.039 | 0.965 | 16 | -0.315 | -28.745 | 48.104 | -0.593 | -29.692 | -0.462 | -8.623 | f9_e5_20,f10_near5,f3_rev20,f10_persist20 |
