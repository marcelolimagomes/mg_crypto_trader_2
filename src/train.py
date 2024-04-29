import sys

from ta.trend import *
from ta.momentum import *
from sklearn.model_selection import train_test_split
from pycaret.classification import ClassificationExperiment
from imblearn.under_sampling import AllKNN

import src.utils as utils
import src.myenv as myenv
import src.calc_utils as calc_utils

import pandas as pd
import numpy as np
import warnings
import traceback
import logging

log = None

SESSION_ID = 123
MODEL = "et"


def get_data(symbol, interval):
  df = utils.get_database(symbol=symbol, interval=interval, columns=myenv.all_klines_cols, parse_dates=False)
  df.drop(
      columns=["open_time", "close_time", "volume", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume",
               "ignore", "symbol",],
      inplace=True, errors="ignore",)
  return df


def feature_engeneering(df, profit_target=0.015, shift_periods=24, dropna=True, status=True):
  # Calc EMA
  # print(">>>>>>>>>>> RANGE", list(range(myenv.min_rsi, myenv.max_rsi + 1, myenv.step_rsi)))
  df = calc_utils.calc_ema_periods(df, list(range(myenv.min_rsi, myenv.max_rsi + 1, myenv.step_rsi)), close_price="close", diff_price=True)
  # Calc RSI
  df = calc_utils.calc_RSI(df, close_price="close", window=14, fillna=False, last_one=False)
  # Calc AMPLITUDE
  df = calc_utils.calc_amplitude(df, column="close")

  # Calc MACD
  macd = MACD(df["close"], 12, 26, 9)
  df["macd"] = macd.macd()
  df["macd_diff"] = macd.macd_diff()
  df["macd_signal"] = macd.macd_signal()

  # Calc Awesome Oscillator
  aoi = AwesomeOscillatorIndicator(df["high"], df["low"])
  df["aoi"] = aoi.awesome_oscillator()

  # Calc TSI
  df["tsi"] = TSIIndicator(df["close"]).tsi()

  if status:
    # Calc Variation and Status
    df["variation"] = (df["close"] - df["close"].shift(shift_periods)) / df["close"]
    df["status"] = np.where(
        df["variation"] > profit_target, "LONG", "STABLE"
    )  # 1 == LONG, 0 == STABLE
    df.drop(columns=["variation"], inplace=True)

  if dropna:
    df.dropna(inplace=True)

  return df


def train(symbol, interval, data, train_size=0.9, shuffle=True, use_gpu=False):
  print(f"Setup Model: train_size: {train_size}, shuffle: {shuffle}, use_gpu: {use_gpu}")
  exp_class = ClassificationExperiment()
  exp_class = exp_class.setup(
      data,
      train_size=train_size,
      data_split_shuffle=shuffle,
      data_split_stratify=shuffle,
      target="status",
      fix_imbalance=True,
      fix_imbalance_method=AllKNN(allow_minority=False, kind_sel="all", n_jobs=-1, n_neighbors=3, sampling_strategy="auto"),
      session_id=SESSION_ID,
      fold=3,
      use_gpu=use_gpu,
  )

  best_model = exp_class.create_model(MODEL)
  final_model = exp_class.finalize_model(best_model)
  model_filename = utils.get_model_name(MODEL, symbol, interval)
  exp_class.save_model(final_model, model_filename)
  log.info(f"Model saved: {model_filename}")


def main(interval_list, log_level):
  global log
  log = utils.configure_log(log_level)
  for interval in interval_list:
    for symbol in utils.get_symbol_list():
      try:
        log.info(f"Start training {symbol} - {interval}")

        log.info(f"Getting data...")
        df = get_data(symbol=symbol, interval=interval)

        periods = utils.get_periods_for_interval(interval)
        log.info(f"Feature engineering for periods: {periods}...")
        df = feature_engeneering(df, shift_periods=periods)

        log.info(f"Training...")
        train(symbol, interval, df)

        log.info(f"Model Trained: {symbol} - {interval}")
      except Exception as e:
        log.exception(e)
        traceback.print_stack()
