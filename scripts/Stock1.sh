python -u run.py \
  --root_path ./dataset/stock1/ \
  --data_path stock1.csv \
  --model_id stock1 \
  --model ETSformer \
  --data stock1 \
  --features S \
  --seq_len 96 \
  --pred_len 7 \
  --e_layers 2 \
  --d_layers 2 \
  --enc_in 7 \
  --dec_in 7 \
  --c_out 7 \
  --des 'Exp' \
  --K 3 \
  --learning_rate 1e-5 \
  --itr 1

