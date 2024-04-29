from binance import ThreadedWebsocketManager, helpers
from datetime import datetime, timedelta

from ta.trend import *
from ta.momentum import *
from pycaret.classification import ClassificationExperiment

import src.utils as utils
import src.myenv as myenv
import src.train as train
import src.send_message as sm

import pandas as pd
import traceback
import time
import threading
# global
balance: float = 0.0


class Bot:

  def __init__(self, params):
    self.mutex = threading.Lock()
    self.symbol = params['symbol']
    self.interval = params['interval']
    self.ix_symbol = f'{self.symbol}_{self.interval}'
    self.verbose = params['verbose']
    self.date_read_kline = datetime(1900, 1, 1)
    self.data = None
    self.target_margin = float(params['target_margin'])
    self.stop_loss_multiplier = int(params['stop_loss_multiplier'])
    self.step_rsi = int(params['step_rsi'])
    self.p_ema = int(params['p_ema'])

    # Initialize logging
    if 'log_level' in params:
      self.log = utils.configure_log(f"BOT", self.symbol, self.interval, params['log_level'])
    else:
      self.log = utils.configure_log(f"BOT", self.symbol, self.interval, myenv.log_level)

    self.model_algorithm = params['model_algorithm']

    self.periods = utils.get_periods_for_interval(self.interval)

    self.log.info(f'Periods: {self.periods}')

    self.log.info(f'Load Model: {self.model_algorithm} - Symbol: {self.symbol} - Interval: {self.interval}')
    self.model_filename = utils.get_model_name(self.model_algorithm, self.symbol, self.interval)
    self.exp = ClassificationExperiment()
    self.model = self.exp.load_model(self.model_filename)

  def update_data_from_web(self):
    self.mutex.acquire()
    self.data = utils.get_klines(symbol=self.symbol, interval=self.interval, max_date=None, limit=350, columns=myenv.all_klines_cols, parse_dates=False)
    # self.data = utils.get_data(self.symbol, self.interval, columns=myenv.all_klines_cols, parse_dates=False, tail=350)
    self.data.drop(columns=["close_time", "volume", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
                            "taker_buy_quote_asset_volume", "ignore"], inplace=True, errors='ignore')
    self.mutex.release()

  def feature_engeneering(self):
    last_update = self.date_read_kline.strftime('%Y-%m-%d %H:%M:%S') if self.date_read_kline is not None else 'None'
    self.log.info(f"Feature engineering for periods: {self.periods} - Last updated: {last_update}")
    try:
      self.mutex.acquire()
      self.data = train.feature_engeneering(self.data, shift_periods=self.periods, dropna=False, status=False)
      self.mutex.release()
    except Exception as error:
      self.log.exception(error)
      if self.mutex.locked():
        self.mutex.release()

  def log_info(self, purchased: bool, open_time, purchased_price: float, actual_price: float, margin_operation: float, amount_invested: float, profit_and_loss: float, balance: float, take_profit: float,
               stop_loss: float, target_margin: float, strategy: str, p_ema_label: str, p_ema_value: float):
    # _open_time = utils.format_date(open_time)

    if purchased:
      msg = f'{self.ix_symbol}: *PURCHASED*: {strategy} TM: {target_margin:.2f}% '
      msg += f'PP: ${purchased_price:.6f} AP: ${actual_price:.6f} MO: {100*margin_operation:.2f}% AI: ${amount_invested:.2f} '
      msg += f'PnL: ${profit_and_loss:.2f} TP: ${take_profit:.6f} SL: ${stop_loss:.6f} B: ${balance:.2f} {p_ema_label}: ${p_ema_value:.6f}'
    # else:
    #    msg = f'[BNC]<NOT PURCHASED>: {self.ix_symbol} AP: ${actual_price:.6f} B: ${balance:.2f} TM: {target_margin:.2f}% {p_ema_label}: ${p_ema_value:.6f}'
    self.log.info(f'{msg}')
    sm.send_status_to_telegram(msg)

  def log_buy(self, open_time, strategy, purchased_price, amount_invested, balance, target_margin, take_profit, stop_loss, rsi, restored=False):
    _open_time = utils.format_date(open_time)
    status = ''
    if restored:
      status = '-RESTORED'

    msg = f'{self.ix_symbol}: *BUYING{status}*:  OT: {_open_time} St: {strategy} TM: {target_margin:.2f}% '
    msg += f'PP: $ {purchased_price:.6f} AI: $ {amount_invested:.2f} TP: $ {take_profit:.6f} '
    msg += f'SL: $ {stop_loss:.6f} RSI: {rsi:.2f} B: $ {balance:.2f}'
    self.log.info(f'{msg}')
    sm.send_to_telegram(msg)

  def log_selling(self, open_time, strategy, purchased_price, actual_price, margin_operation, amount_invested, profit_and_loss, balance, take_profit,
                  stop_loss, target_margin, rsi):
    _open_time = utils.format_date(open_time)

    msg = f'{self.ix_symbol}: {strategy} *SELLING* OT: {_open_time} TM: {target_margin:.2f}% '
    msg += f'PP: $ {purchased_price:.6f} AP: $ {actual_price:.6f} MO: {100*margin_operation:.2f}% AI: $ {amount_invested:.2f} '
    msg += f'TP: $ {take_profit:.6f} SL: $ {stop_loss:.6f} RSI: {rsi:.2f} B: $ {balance:.2f} PnL O: $ {profit_and_loss:.2f} '
    self.log.info(f'{msg}')
    sm.send_to_telegram(msg)

  def validate_short_or_long(self, strategy):
    return strategy.startswith('LONG') or strategy.startswith('SHORT')

  def is_long(self, strategy):
    return strategy.startswith('LONG')

  def is_short(self, strategy):
    return strategy.startswith('SHORT')

  def handle_socket_kline(self, msg):
    try:
      if self.data is not None:
        self.log.debug(f'handle_socket_kline:{msg}')
        df_klines = utils.parse_kline_from_stream(pd.DataFrame(data=[msg['k']]), maintain_cols=self.data.columns)
        df_klines = utils.parse_type_fields(df_klines, parse_dates=False)
        df_klines = utils.adjust_index(df_klines)
        self.log.info(f'handle_socket_kline: df_klines.shape: {df_klines.shape}') if self.verbose else None
        df_klines.info() if self.verbose else None

        self.mutex.acquire()
        self.data = pd.concat([self.data, df_klines])
        self.data.drop_duplicates(keep='last', subset=['open_time'], inplace=True)
        self.data.sort_index(inplace=True)
        self.mutex.release()

        self.log.info(f'handle_socket_kline: Updated - _all_data.shape: {self.data.shape}') if self.verbose else None
        self.data.info() if self.verbose else None
        self.date_read_kline = datetime.now()
    except Exception as e:
      self.log.error(f'***ERROR*** handle_socket_kline: {e}')
      sm.send_status_to_telegram(f'{self.ix_symbol} ***ERROR*** handle_socket_kline: {e}')
      if self.mutex.locked():
        self.mutex.release()

  def run(self):
    key, sec = utils.get_keys()
    twm = ThreadedWebsocketManager(key, sec, requests_params={'timeout': 20})
    twm.start()
    msg_log = twm.start_kline_socket(callback=self.handle_socket_kline, symbol=self.symbol, interval=self.interval)
    self.log.info(f'ThreadedWebsocketManager: {msg_log}')
    # print('<<<<<self.symbol>>>>', self.symbol)
    symbol_info, symbol_precision, quote_precision, quantity_precision, price_precision, step_size, tick_size = utils.get_symbol_info(self.symbol)
    cont = 0
    cont_aviso = 101
    purchased = False
    purchased_price = 0.0
    executed_qty = 0.0
    actual_price = 0.0
    amount_invested = 0.0
    amount_to_invest = 0.0
    take_profit = 0.0
    stop_loss = 0.0
    profit_and_loss = 0.0
    strategy = ''
    margin_operation = 0.0
    target_margin = 0.0
    rsi = 0.0
    p_ema_label = f'ema_{myenv.p_ema}p'
    p_ema_value = 0.0
    order_buy_id = None

    global balance
    balance = utils.get_account_balance()  # ok
    self.log.info(f'{self.ix_symbol}: Initial Account Balance: ${balance}')
    target_margin = self.target_margin

    purchased_aux = False
    purchased_price_aux = 0.00
    margin_operation_aux = 0.00
    profit_and_loss_aux = 0.00
    amount_invested_aux = 0.00
    strategy_aux = 'LONG'  # At time, only LONG is available
    take_profit_aux = 0.00
    stop_loss_aux = 0.00

    no_ammount_to_invest_count = 0

    while True:
      try:
        seconds_after_last_update = datetime.now() - self.date_read_kline
        if seconds_after_last_update.seconds >= 60:
          self.log.info(f'Updating data for Symbol: {self.ix_symbol} after {seconds_after_last_update.seconds} seconds')
          sm.send_status_to_telegram(f'Updating data for Symbol: {self.ix_symbol} after {seconds_after_last_update.seconds} seconds')
          self.update_data_from_web()
          self.log.info(f'Data Shape[{self.ix_symbol}]: {self.data.shape}')
          sm.send_status_to_telegram(f'Data Shape[{self.ix_symbol}]: {self.data.shape}')

        self.feature_engeneering()
        pred = self.model.predict(self.data.tail(1).drop(columns=['open_time'], errors='ignore'))
        strategy = pred.values[0]
        actual_price, open_time, rsi, p_ema_value = self.data.tail(1)['close'].values[0], self.data.tail(1)['open_time'].values[0], self.data.tail(1)['rsi'].values[0], self.data.tail(1)[p_ema_label].values[0]
        _open_time = utils.format_date(open_time)

        # COPY BUY LOGIC
        self.log.info(f'{strategy} OT: {_open_time} AP: {actual_price:.{symbol_precision}f} RSI: {rsi:.2f}%  {p_ema_label}: ${p_ema_value:.{symbol_precision}f}')
        if self.is_long(strategy):  # Only BUY with LONG strategy. If true, BUY
          purchased, order_sell_limit, take_profit = utils.status_order_limit(self.symbol, self.interval)
          self.log.info(f'Purchased: {purchased} - TM: {target_margin:.2f}% - B: ${balance:.{quote_precision}f}')
          if not purchased:
            amount_to_invest, balance = utils.get_amount_to_invest()  # ok
            if amount_to_invest > myenv.min_amount_to_invest:
              take_profit, stop_loss = utils.calc_take_profit_stop_loss(strategy, actual_price, target_margin, self.stop_loss_multiplier)  # ok
              ledger_params = utils.get_params_operation(open_time, self.symbol, self.interval, 'BUY', target_margin, amount_to_invest,
                                                         take_profit, stop_loss, actual_price, rsi, 0.0, 0.0, 0.0, strategy, balance,
                                                         symbol_precision, quote_precision, quantity_precision, price_precision, step_size, tick_size)  # ok
              self.log.info(f'>>> ledger_params: {ledger_params}')
              status_buy, order_buy_id, order_sell_id = utils.register_operation(ledger_params)
              if order_buy_id is not None:
                purchased_price = float(order_buy_id['price'])
                executed_qty = float(order_buy_id['executedQty'])
                amount_invested = purchased_price * executed_qty

                msg = f'{self.ix_symbol}-{strategy}: *ORDER BUY* - {status_buy} OT: {_open_time} AP: ${actual_price:.{symbol_precision}f} PP: ${purchased_price:.{symbol_precision}f} AI: ${amount_to_invest:.2f} '
                msg += f'TP: ${take_profit:.{symbol_precision}f} SL: ${stop_loss:.{symbol_precision}f} {p_ema_label}: ${p_ema_value:.{symbol_precision}f} '
                msg += f'TM: {target_margin:.2f}% RSI: {rsi:.2f}% B: ${balance:.{quote_precision}f} SELL: {"OK" if order_sell_id is not None else "ERROR"} '
                sm.send_to_telegram(msg)
                self.log.debug(msg)
            else:
              msg = f'No Amount to invest: ${balance:.{quote_precision}f} Min: ${myenv.min_amount_to_invest:.{quote_precision}f} '
              self.log.warn(msg)
              no_ammount_to_invest_count += 1

        cont_aviso += 1
        if cont_aviso > 100:  # send status to telegram each x loop
          cont_aviso = 0
          purchased, _, take_profit = utils.status_order_limit(self.symbol, self.interval)
          if purchased:
            _, _, purchased_price, executed_qty, amount_invested = utils.status_order_buy(self.symbol, self.interval)
            _, _, stop_loss = utils.status_order_stop(self.symbol, self.interval)
            margin_operation = (actual_price - purchased_price) / purchased_price
            profit_and_loss = amount_invested * margin_operation

            self.log_info(purchased, open_time, purchased_price, actual_price, margin_operation, amount_invested, profit_and_loss, balance,
                          take_profit, stop_loss, target_margin, strategy, p_ema_label, p_ema_value)

            strategy_aux = 'LONG'
            purchased_aux = True
            purchased_price_aux = purchased_price
            margin_operation_aux = margin_operation
            profit_and_loss_aux = profit_and_loss
            amount_invested_aux = amount_invested
            take_profit_aux = take_profit
            stop_loss_aux = stop_loss
          elif purchased_aux and take_profit != 0.0:
            purchased_aux = False
            self.log_selling(open_time, strategy_aux, purchased_price_aux, actual_price, margin_operation_aux, amount_invested_aux,
                             profit_and_loss_aux, balance, take_profit_aux, stop_loss_aux, target_margin, rsi)

          if no_ammount_to_invest_count > 0:
            msg = f'No Amount to invest :Tryed {no_ammount_to_invest_count} times.  ${balance:.{quote_precision}f} Min: ${myenv.min_amount_to_invest:.{quote_precision}f} '
            sm.send_status_to_telegram(f'{self.ix_symbol}: {msg}')
            no_ammount_to_invest_count = 0

      except Exception as e:
        traceback.print_stack()
        err_msg = f'ERROR: symbol: {self.ix_symbol} - Exception: {e}'
        self.log.exception(err_msg)
        sm.send_status_to_telegram(err_msg)
        if self.mutex.locked():
          self.mutex.release()
      finally:
          # Sleep in each loop
        time.sleep(myenv.sleep_refresh)
