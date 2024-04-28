import sys
import os

from binance import ThreadedWebsocketManager, helpers

from ta.trend import *
from ta.momentum import *
from pycaret.classification import ClassificationExperiment

import src.utils as utils
import src.myenv as myenv
import src.calc_utils as calc_utils
import src.train as train

import pandas as pd
import numpy as np
import traceback
import time
import threading


class Bot:

  def __init__(self, params):
    self.symbol = params['symbol']
    self.interval = params['interval']
    self.ix_symbol = f'{self.symbol}_{self.interval}'
    self.verbose = params['verbose']

    # Initialize logging
    if 'log_level' in params:
      print('LOG_LEVEL:', params['log_level'])
      self.log = utils.configure_log(f"BOT", self.symbol, self.interval, params['log_level'])
    else:
      self.log = utils.configure_log(f"BOT", self.symbol, self.interval, myenv.log_level)

    self.model_algorithm = params['model_algorithm']

    self.log.info(f'Download data for Symbol: {self.symbol} - Interval: {self.interval}')
    self.data = utils.get_data(self.symbol, self.interval, columns=myenv.all_klines_cols, parse_dates=False, tail=350)
    self.data.drop(columns=["close_time", "volume", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
                            "taker_buy_quote_asset_volume", "ignore", "symbol"], inplace=True, errors='ignore')
    self.log.info(f'Data Shape[{self.ix_symbol}]: {self.data.shape}')
    self.periods = utils.get_periods_for_interval(self.interval)

    self.log.info(f'Periods: {self.periods}')

    self.log.info(f'Load Model: {self.model_algorithm} - Symbol: {self.symbol} - Interval: {self.interval}')
    self.model_filename = utils.get_model_name(self.model_algorithm, self.symbol, self.interval)
    self.exp = ClassificationExperiment()
    self.model = self.exp.load_model(self.model_filename)

    self.mutex = threading.Lock()

  def feature_engeneering(self):
    self.log.info(f"Feature engineering for periods: {self.periods}...")
    try:
      self.data = train.feature_engeneering(self.data, shift_periods=self.periods, dropna=False, status=False)
    except Exception as error:
      self.log.exception(error)

  def handle_socket_kline(self, msg):
    try:
      self.log.debug(f'handle_socket_kline:{msg}')
      df_klines = utils.parse_kline_from_stream(pd.DataFrame(data=[msg['k']]), maintain_cols=self.data.columns)
      df_klines = utils.parse_type_fields(df_klines, parse_dates=False)
      df_klines = utils.adjust_index(df_klines)
      self.log.info(f'handle_socket_kline: df_klines.shape: {df_klines.shape}') if self.verbose else None
      df_klines.info() if self.verbose else None

      self.mutex.acquire()
      if self.data is not None:
        self.data = pd.concat([self.data, df_klines])
        self.data.drop_duplicates(keep='last', subset=['open_time'], inplace=True)
        self.data.sort_index(inplace=True)
        self.log.info(f'handle_socket_kline: Updated - _all_data.shape: {self.data.shape}') if self.verbose else None
        self.data.info() if self.verbose else None
      self.mutex.release()
    except Exception as e:
      self.log.error(f'***ERROR*** handle_socket_kline: {e}')
      # sm.send_status_to_telegram(f'{self.ix} ***ERROR*** handle_socket_kline: {e}')
      if self.mutex.locked():
        self.mutex.release()

  def run(self):
    key, sec = utils.get_keys()
    self.log.info(f'run: {key} - {sec}')
    twm = ThreadedWebsocketManager(key, sec, requests_params={'timeout': 20})
    twm.start()
    msg_log = twm.start_kline_socket(callback=self.handle_socket_kline, symbol=self.symbol, interval=self.interval)
    self.log.info(f'ThreadedWebsocketManager: {msg_log}')

    while True:
      try:
        self.feature_engeneering()
        self.log.info(f'Data Shape[{self.ix_symbol}]: {self.data.shape}')
      except Exception as e:
        traceback.print_stack()
        err_msg = f'ERROR: symbol: {self._symbol} - interval: {self._interval} - Exception: {e}'
        self.log.exception(err_msg)
        # sm.send_status_to_telegram(err_msg)
        if self.mutex.locked():
          self.mutex.release()
      finally:
          # Sleep in each loop
        time.sleep(myenv.sleep_refresh)
