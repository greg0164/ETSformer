python -u run.py --root_path ./dataset/Stock1/ --data_path stock1.csv --model_id stock1 --model ETSformer --data custom --features MS --target Close --freq d --seq_len 96 --pred_len 2 --d_model 256 --e_layers 2 --d_layers 2 --d_ff 2048 --enc_in 9 --dec_in 9 --c_out 9 --des 'Exp' --K 3 --learning_rate 1e-5 --itr 1
