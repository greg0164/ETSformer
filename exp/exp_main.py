from models import ETSformer
from data_provider.data_factory import data_provider
from exp.exp_basic import Exp_Basic
from utils.tools import EarlyStopping, adjust_learning_rate
from utils.metrics import metric
from utils.Adam import Adam

import numpy as np
import torch
import torch.nn as nn

import os
import time

import warnings
import numpy as np

warnings.filterwarnings('ignore')


class Exp_Main(Exp_Basic):
    def __init__(self, args):
        super(Exp_Main, self).__init__(args)

    def _build_model(self):
        model_dict = {
            'ETSformer': ETSformer,
        }
        model = model_dict[self.args.model](self.args).float()

        if self.args.use_multi_gpu and self.args.use_gpu:
            model = nn.DataParallel(model, device_ids=self.args.device_ids)
        return model

    def _get_data(self, flag):
        data_set, data_loader = data_provider(self.args, flag)
        return data_set, data_loader

    def _select_optimizer(self):
        if 'warmup' in self.args.lradj:
            lr = self.args.min_lr
        else:
            lr = self.args.learning_rate

        if self.args.smoothing_learning_rate > 0:
            smoothing_lr = self.args.smoothing_learning_rate
        else:
            smoothing_lr = 100 * self.args.learning_rate

        if self.args.damping_learning_rate > 0:
            damping_lr = self.args.damping_learning_rate
        else:
            damping_lr = 100 * self.args.learning_rate

        nn_params = []
        smoothing_params = []
        damping_params = []
        for k, v in self.model.named_parameters():
            if k[-len('_smoothing_weight'):] == '_smoothing_weight':
                smoothing_params.append(v)
            elif k[-len('_damping_factor'):] == '_damping_factor':
                damping_params.append(v)
            else:
                nn_params.append(v)

        model_optim = Adam([
            {'params': nn_params, 'lr': lr, 'name': 'nn'},
            {'params': smoothing_params, 'lr': smoothing_lr, 'name': 'smoothing'},
            {'params': damping_params, 'lr': damping_lr, 'name': 'damping'},
        ])

        return model_optim

    def _select_criterion(self):
        criterion = nn.MSELoss()
        return criterion

    def vali(self, vali_data, vali_loader, criterion):
        total_loss = []
        self.model.eval()
        with torch.no_grad():
            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(vali_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float()

                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)
                # encoder - decoder
                outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)
                f_dim = -1 if self.args.features == 'MS' else 0
                batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)

                pred = outputs.detach().cpu()
                true = batch_y.detach().cpu()

                loss = criterion(pred, true)

                total_loss.append(loss)
        total_loss = np.average(total_loss)
        self.model.train()
        return total_loss

    def train(self, setting):
        train_data, train_loader = self._get_data(flag='train')
        vali_data, vali_loader = self._get_data(flag='val')
        test_data, test_loader = self._get_data(flag='test')

        path = os.path.join(self.args.checkpoints, setting)
        if not os.path.exists(path):
            os.makedirs(path)

        time_now = time.time()

        # print(train_loader)
        train_steps = len(train_loader)
        # print(f'train_steps={train_steps}')
        # print(f'len train_data={len(train_data)}')
        # print(f'batch_size={train_loader.batch_size}')
        # print('before iterating the train loader')
        # iter(train_loader).next()
        # print('after iterating the train loader')

        early_stopping = EarlyStopping(patience=self.args.patience, verbose=True)

        model_optim = self._select_optimizer()
        criterion = self._select_criterion()

        for epoch in range(self.args.train_epochs):
            iter_count = 0
            train_loss = []

            self.model.train()
            epoch_time = time.time()
            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(train_loader):
                # print(f'i {i} batch_x {batch_x} batch_y {batch_y} batch_x_mark {batch_x_mark} batch_y_mark {batch_y_mark}')
                iter_count += 1
                model_optim.zero_grad()
                batch_x = batch_x.float().to(self.device)

                batch_y = batch_y.float().to(self.device)
                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)

                # encoder - decoder
                outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)

                f_dim = -1 if self.args.features == 'MS' else 0
                batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)
                loss = criterion(outputs, batch_y)
                train_loss.append(loss.item())

                if (i + 1) % 100 == 0:
                    print("\titers: {0}, epoch: {1} | loss: {2:.7f}".format(i + 1, epoch + 1, loss.item()))
                    speed = (time.time() - time_now) / iter_count
                    left_time = speed * ((self.args.train_epochs - epoch) * train_steps - i)
                    print('\tspeed: {:.4f}s/iter; left time: {:.4f}s'.format(speed, left_time))
                    iter_count = 0
                    time_now = time.time()

                loss.backward()
                torch.nn.utils.clip_grad_norm(self.model.parameters(), 1.0)
                model_optim.step()

            print("Epoch: {} cost time: {}".format(epoch + 1, time.time() - epoch_time))
            train_loss = np.average(train_loss)
            vali_loss = self.vali(vali_data, vali_loader, criterion)
            test_loss = self.vali(test_data, test_loader, criterion)

            print("Epoch: {0}, Steps: {1} | Train Loss: {2:.7f} Vali Loss: {3:.7f} Test Loss: {4:.7f}".format(
                epoch + 1, train_steps, train_loss, vali_loss, test_loss))
            early_stopping(vali_loss, self.model, path)
            if early_stopping.early_stop:
                print("Early stopping")
                break

            adjust_learning_rate(model_optim, epoch + 1, self.args)

        best_model_path = path + '/' + 'checkpoint.pth'
        self.model.load_state_dict(torch.load(best_model_path))

        return self.model

    def test(self, setting, data, save_vals=False):
        """data - 'val' or 'test' """
        test_data, test_loader = self._get_data(flag=data)

        print('loading model')
        self.model.load_state_dict(torch.load(os.path.join('./checkpoints/' + setting, 'checkpoint.pth')))

        preds = []
        trues = []

        self.model.eval()
        with torch.no_grad():
            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(test_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)

                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)
                # encoder - decoder
                outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)

                f_dim = -1 if self.args.features == 'MS' else 0
                outputs = outputs[:, -self.args.pred_len:, f_dim:]
                batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)
                outputs = outputs.detach().cpu().numpy()
                batch_y = batch_y.detach().cpu().numpy()

                pred = outputs
                true = batch_y

                preds.append(pred)
                trues.append(true)

        preds = np.array(preds)
        trues = np.array(trues)
        # print('test shape:', preds.shape, trues.shape)
        preds = preds.reshape(-1, preds.shape[-2], preds.shape[-1])
        trues = trues.reshape(-1, trues.shape[-2], trues.shape[-1])
        # print('test shape:', preds.shape, trues.shape)
        print(preds[:10]);
        print(trues[:10]);

        # result save
        folder_path = './results/' + setting + '/'
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        mae, mse, rmse, mape, mspe = metric(preds, trues)
        print('mse:{}, mae:{}, mape:{}'.format(mse, mae, mape))
        # Calculate the number of elements for the top and bottom 5%
        preds=preds.reshape(-1)
        trues=trues.reshape(-1)
        num_elements = len(trues)
        # this code was specific to predicting the % change - and we were analyzing the top 5 and bottom 5 % change days
        # top_5_percent_count = int(0.05 * num_elements)
        # bottom_5_percent_count = int(0.05 * num_elements)

        # Get the sorted indices
        # sorted_indices = np.argsort(trues)

        # Get the indices of the top and bottom 5% of values in trues
        # top_5_percent_indices = sorted_indices[-top_5_percent_count:]
        # print(f'top_5_percent_indices={top_5_percent_indices}')
        # bottom_5_percent_indices = sorted_indices[:bottom_5_percent_count]
        # print(f'bottom_5_percent_indices={bottom_5_percent_indices}')

        # Calculate the MAPE for the top and bottom 5%
        # mape_top_5_percent = np.mean(np.abs((preds[top_5_percent_indices] - trues[top_5_percent_indices]) / trues[top_5_percent_indices])) * 100
        # mape_bottom_5_percent = np.mean(np.abs((preds[bottom_5_percent_indices] - trues[bottom_5_percent_indices]) / trues[bottom_5_percent_indices])) * 100

        # Calculate the sign match for the top and bottom 5%
        # top_sign_match = np.sign(preds[top_5_percent_indices]) == np.sign(trues[top_5_percent_indices])
        # bottom_sign_match = np.sign(preds[bottom_5_percent_indices]) == np.sign(trues[bottom_5_percent_indices])

        # Calculate the percentage of sign match for the top and bottom 5%
        # percentage_top_sign_match = (np.sum(top_sign_match) / top_5_percent_count) * 100 if top_5_percent_count > 0 else 0
        # percentage_bottom_sign_match = (np.sum(bottom_sign_match) / bottom_5_percent_count) * 100 if bottom_5_percent_count > 0 else 0

        # Print the MAPE and sign match percentages
        # print("MAPE for Top 5%:", mape_top_5_percent)
        # print("MAPE for Bottom 5%:", mape_bottom_5_percent)
        # print("Percentage of Sign Match for Top 5%:", percentage_top_sign_match, "%")
        # print percentage of sign match for bottom 5%
        print("Percentage of Sign Match (% time directionally correct):", np.sum(((trues > 0.0) & (preds > 0.0)) | ((trues <= 0.0) & (preds <= 0.0)))/num_elements, "%")
        # Compare signs and store as Boolean values
        # sign_comparison = np.sign(preds) == np.sign(trues)

        # Count the number of False elements
        # count_false = np.count_nonzero(~sign_comparison)  # ~ is used to invert the Boolean array

        # Calculate the percentage of False elements
        # percentage_false = (count_false / len(sign_comparison)) * 100

        # print("Number of sign mismatched elements:", count_false)
        # print("Percentage of sign mismatch:", percentage_false, "%")

        np.save(folder_path + f'{data}_metrics.npy', np.array([mae, mse, rmse, mape, mspe]))

        if save_vals:
            np.save(folder_path + 'pred.npy', preds)
            np.save(folder_path + 'true.npy', trues)

        return
