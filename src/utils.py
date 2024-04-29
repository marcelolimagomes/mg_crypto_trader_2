from binance import AsyncClient as Client
from binance.exceptions import BinanceAPIException

import pandas as pd
import os
import sys
import traceback
import logging
import pytz
import time
import numpy as np

import src.myenv as myenv
import src.send_message as sm

from datetime import datetime, timedelta
from multiprocessing import Pool

import asyncio

loop = asyncio.new_event_loop()

log = logging.getLogger()
client: Client = None

SESSION_ID = 123


def get_telegram_key():
  with open(f'{sys.path[0]}/telegram.key', 'r') as file:
    first_line = file.readline()
    if not first_line:
      raise Exception('telegram.key is empty')
  return first_line


def date_parser(x):
  return pd.to_datetime(x, unit='ms')


def get_periods_for_interval(interval):
  match interval:
    case '30m':
      return 24 * 2
    case '1h':
      return 24


def get_start_date_for_interval(interval):
  date = None
  match interval:
    case '1m':
      date = datetime.now(pytz.utc) - timedelta(days=myenv.days_to_validate_train + 1)  # 6 Months # 250p = 4,17h = 0,17d
    case '5m':
      date = datetime.now(pytz.utc) - timedelta(days=myenv.days_to_validate_train + 2)  # 9 Months # 250p = 20,83h = 0,87d
    case '15m':
      date = datetime.now(pytz.utc) - timedelta(days=myenv.days_to_validate_train + 6)  # 2 Years # 250p = 62,5h = 2,60d
    case '30m':
      date = datetime.now(pytz.utc) - timedelta(days=myenv.days_to_validate_train + 12)  # 3 Years # 250p = 125h = 5,21d
    case '1h':
      date = datetime.now(pytz.utc) - timedelta(days=myenv.days_to_validate_train + 24)  # 6 Years # 250p = 250h = 10,42d

  return int(date.timestamp() * 1000), date


def get_symbol_list():
  result = []
  df = pd.read_csv(myenv.datadir + '/symbol_list.csv')
  for symbol in df['symbol']:
    result.append(symbol)
  return result


def get_symbol_list_best_params_index():
  result = []
  df = pd.read_csv(myenv.datadir + '/top_params_index.csv')
  for symbol in df['symbol']:
    if symbol not in result:
      result.append(symbol)
  return result


def get_max_date(df_database, start_date='2010-01-01'):
  max_date = datetime.strptime(start_date, '%Y-%m-%d')
  if df_database is not None and df_database.shape[0] > 0:
    max_date = pd.to_datetime(df_database['open_time'].max(), unit='ms')
  return max_date


def get_database_name(symbol, interval):
  return f'{myenv.datadir}/{symbol}/{symbol}_{interval}.dat'


def get_database(symbol, interval='1h', tail=-1, columns=['open_time', 'close'], parse_dates=True):
  database_name = get_database_name(symbol, interval)
  log.info(f'get_database: name: {database_name}')

  df_database = pd.DataFrame()
  log.info(f'get_database: columns: {columns}')
  if os.path.exists(database_name):
    if parse_dates:
      df_database = pd.read_csv(database_name, sep=';', parse_dates=myenv.date_features, date_parser=date_parser, decimal='.', usecols=columns, )
    else:
      df_database = pd.read_csv(database_name, sep=';', decimal='.', usecols=columns, )
    df_database = parse_type_fields(df_database, parse_dates)
    df_database = adjust_index(df_database)
    df_database = df_database[columns]
  if tail > 0:
    df_database = df_database.tail(tail)
  log.info(f'get_database: count_rows: {df_database.shape[0]} - symbol: {symbol}_{interval} - tail: {tail}')
  log.info(f'get_database: duplicated: {df_database.index.duplicated().sum()}')
  return df_database


def adjust_index(df):
  df.drop_duplicates(keep='last', subset=['open_time'], inplace=True)
  df.index = df['open_time']
  df.index.name = 'ix_open_time'
  df.sort_index(inplace=True)
  return df


def parse_type_fields(df, parse_dates=False):
  try:
    if 'symbol' in df.columns:
      df['symbol'] = pd.Categorical(df['symbol'])

    for col in myenv.float_kline_cols:
      if col in df.columns:
        if df[col].isna().sum() == 0:
          df[col] = df[col].astype('float32')

    for col in myenv.float_kline_cols:
      if col in df.columns:
        if df[col].isna().sum() == 0:
          df[col] = df[col].astype('float32')

    for col in myenv.integer_kline_cols:
      if col in df.columns:
        if df[col].isna().sum() == 0:
          df[col] = df[col].astype('int16')

    if parse_dates:
      for col in myenv.date_features:
        if col in df.columns:
          if df[col].isna().sum() == 0:
            df[col] = pd.to_datetime(df[col], unit='ms')

  except Exception as e:
    log.exception(e)
    traceback.print_stack()

  return df


def get_data(symbol, save_database=False, interval='1h', tail=-1, columns=['open_time', 'close'], parse_dates=True, updata_data_from_web=True, start_date='2010-01-01'):
  database_name = get_database_name(symbol, interval)
  log.info(f'get_data: Loading database: {database_name}')
  df_database = get_database(symbol=symbol, interval=interval, tail=tail, columns=columns, parse_dates=parse_dates)
  log.info(f'Shape database on disk: {df_database.shape}')

  log.info(f'Filtering start date: {start_date}')
  max_date = None
  if df_database.shape[0] > 0 and parse_dates:
    df_database = df_database[df_database['open_time'] >= start_date]
    log.info(f'New shape after filtering start date. Shape: {df_database.shape}')
    max_date = get_max_date(df_database, start_date=start_date)

  max_date_aux = ''
  new_data = False
  if updata_data_from_web:
    log.info(f'get_data: Downloading data for symbol: {symbol} - max_date: {max_date}')
    while (max_date != max_date_aux):
      new_data = True
      log.info(f'get_data: max_date: {max_date} - max_date_aux: {max_date_aux}')
      max_date_aux = get_max_date(df_database, start_date=start_date)
      log.info(f'get_data: Max date database: {max_date_aux}')

      df_klines = get_klines(symbol, interval=interval, max_date=max_date_aux.strftime('%Y-%m-%d'), columns=columns, parse_dates=parse_dates)
      df_database = pd.concat([df_database, df_klines])
      df_database.drop_duplicates(keep='last', subset=['open_time'], inplace=True)
      df_database.sort_index(inplace=True)
      df_database['symbol'] = symbol
      max_date = get_max_date(df_database)

  if save_database and new_data:
    sulfix_name = f'{symbol}_{interval}.dat'
    if not os.path.exists(database_name.removesuffix(sulfix_name)):
      os.makedirs(database_name.removesuffix(sulfix_name))
    df_database.to_csv(database_name, sep=';', index=False, )
    log.info(f'get_data: Database updated at {database_name}')

  log.info(f'New shape after get_data: {df_database.shape}')
  if tail > 0:
    df_database = df_database.tail(tail)
  return df_database


def remove_cols_for_klines(columns):
  cols_to_remove = ['symbol', 'rsi']
  for col in columns:
    if col.startswith('ema'):
      cols_to_remove.append(col)
  for col in cols_to_remove:
    if col in columns:
      columns.remove(col)
  return columns


def get_klines(symbol, interval='1h', max_date='2010-01-01', limit=1000, columns=['open_time', 'close'], parse_dates=True):
    # return pd.DataFrame()
  start_time = datetime.now()
  klines = loop.run_until_complete(get_client().get_historical_klines(symbol=symbol, interval=interval, start_str=max_date, limit=limit))

  columns = remove_cols_for_klines(columns)

  # log.info('get_klines: columns: ', columns)
  df_klines = pd.DataFrame(data=klines, columns=myenv.all_klines_cols)[columns]
  df_klines = parse_type_fields(df_klines, parse_dates=parse_dates)
  df_klines = adjust_index(df_klines)
  delta = datetime.now() - start_time
  # Print the delta time in days, hours, minutes, and seconds
  log.debug(f'get_klines: shape: {df_klines.shape} - Delta time: {delta.seconds % 60} seconds')
  return df_klines


def download_data(save_database=True, parse_dates=False, interval='1h', tail=-1, start_date='2010-01-01', only_best_params=False):
  if only_best_params:
    symbols = get_symbol_list_best_params_index()
  else:
    symbols = get_symbol_list()

  with Pool(processes=(os.cpu_count() * 2)) as pool:
    process_list = []
    results = []
    for symbol in symbols:
      print(f'Download data for symbols: {symbols}')
      print((symbol, save_database, interval, tail, myenv.all_klines_cols, parse_dates, True, start_date))
      process = pool.apply_async(func=get_data, args=(symbol, save_database, interval, tail, myenv.all_klines_cols, parse_dates, True, start_date))
      print(process)
      process_list.append({'key': f'{symbol}_{interval}', 'process': process})
      # get_data(symbol=symbol, save_database=save_database, interval=interval, tail=tail, columns=myenv.all_klines_cols, parse_dates=parse_dates, start_date=start_date)
    for p in process_list:
      try:
        res = p['process'].get()
        print(res)
        log.info(f'Download data finished for: {p["key"]} - Shape: {res.shape}')
        results.append(f'{p["key"]}')
      except Exception as e:
        log.exception(e)
        # traceback.print_stack()
    log.info(f'Results of Download Data: \n{results}')


def get_model_name(model, symbol, interval):
  return f'{myenv.datadir}/{symbol}/{model}_{symbol}_{interval}'


def get_keys():
  with open(f'{sys.path[0]}/mg.key', 'r') as file:
    first_line = file.readline()
    if not first_line:
      raise Exception('mg.key is empty')
    key = first_line.split('##$$')[0]
    sec = first_line.split('##$$')[1]
    return key, sec


def parse_kline_from_stream(df_stream_kline: pd.DataFrame, maintain_cols=['open_time', 'close', 'symbol']):
  rename = {
   't': 'open_time',  # Kline start time
   'T': 'close_time',  # Kline close time
   's': 'symbol',  # Symbol
   'i': 'interval',  # Interval
   'f': 'first_trade_id',  # First trade ID
   'L': 'last_trade_id',  # Last trade ID
   'o': 'open',  # Open price
   'c': 'close',  # Close price
   'h': 'high',  # High price
   'l': 'low',  # Low price
   'v': 'base_asset_volume',    # Base asset volume
   'n': 'number_of_trades',       # Number of trades
   'x': 'is_closed',     # Is this kline closed?
   'q': 'quote_asset_volume',  # Quote asset volume
   'V': 'taker_buy_base_asset_volume',     # Taker buy base asset volume
   'Q': 'taker_buy_quote_asset_volume',   # Taker buy quote asset volume
   'B': 'ignore'   # Ignore
      }
  df_stream_kline.rename(columns=rename, inplace=True, errors='ignore')
  del_cols = []
  for key in df_stream_kline.columns:
    if key not in maintain_cols:
      del_cols.append(key)

  df_stream_kline.drop(columns=del_cols, inplace=True, errors='ignore')
  return df_stream_kline


def parse_type_fields(df, parse_dates=False):
  try:
    if 'symbol' in df.columns:
      df['symbol'] = pd.Categorical(df['symbol'])

    for col in myenv.float_kline_cols:
      if col in df.columns:
        if df[col].isna().sum() == 0:
          df[col] = df[col].astype('float32')

    for col in myenv.integer_kline_cols:
      if col in df.columns:
        if df[col].isna().sum() == 0:
          df[col] = df[col].astype('int16')

    if parse_dates:
      for col in myenv.date_features:
        if col in df.columns:
          if df[col].isna().sum() == 0:
            df[col] = pd.to_datetime(df[col], unit='ms')

  except Exception as e:
    log.exception(e)
    traceback.print_stack()

  return df


def adjust_index(df):
  df.drop_duplicates(keep='last', subset=['open_time'], inplace=True)
  df.index = df['open_time']
  df.index.name = 'ix_open_time'
  df.sort_index(inplace=True)
  return df


def configure_log(name="MAIN", symbol=None, interval=None, log_level=logging.INFO):
  format_date = f'%Y-%m-%d %H:%M:%S'
  if symbol is not None:
    format_msg = f'[%(asctime)s] - %(levelname)s - {name}: {symbol}-{interval} - %(message)s'
    complete_name = f'{name}_{symbol}_{interval}'
  else:
    format_msg = f'[%(asctime)s] - %(levelname)s - %(message)s'
    complete_name = f'{name}'

  log_file_path = os.path.join(myenv.logdir, f'{complete_name}.log')
  logger = logging.getLogger(f'{complete_name}')
  logger.propagate = False
  logger.setLevel(log_level)
  fh = logging.FileHandler(log_file_path, mode='a', delay=True)
  fh.setFormatter(logging.Formatter(format_msg, format_date))
  fh.setLevel(log_level)

  sh = logging.StreamHandler()
  sh.setFormatter(logging.Formatter(format_msg, format_date))
  sh.setLevel(log_level)

  logger.addHandler(fh)
  logger.addHandler(sh)
  print(f'>>>Configure Log: Name: {complete_name} - Level: {log_level}')
  return logger


def login_binance() -> Client:
  key, sec = get_keys()
  _client = loop.run_until_complete(Client.create(key, sec, requests_params={'timeout': 20}, loop=loop))
  print('>>>> LOGIN', _client)
  # _client.REQUEST_TIMEOUT = 20
  return _client


def get_client() -> Client:
  global client
  if client is None:
    client = login_binance()
    log.debug(f'New Instance of Client: {client}')
    print(f'New Instance of Client: {client}')

  return client


def get_precision(tick_size: float) -> int:
  result = 8
  if tick_size >= 1.0:
    result = 0
  elif tick_size >= 0.1:
    result = 1
  elif tick_size >= 0.01:
    result = 2
  elif tick_size >= 0.001:
    result = 3
  elif tick_size >= 0.0001:
    result = 4
  elif tick_size >= 0.00001:
    result = 5
  elif tick_size >= 0.000001:
    result = 6
  elif tick_size >= 0.0000001:
    result = 7
  return result


def get_account_balance(asset=myenv.asset_balance_currency):
  asset_balance = loop.run_until_complete(get_client().get_asset_balance(asset, recvWindow=myenv.recv_window))
  balance = float(asset_balance['free'])

  return balance


def get_amount_to_invest():
  balance = get_account_balance()
  amount_invested = 0.0

  if balance >= myenv.min_amount_to_invest:
    if balance >= myenv.default_amount_to_invest:
      amount_invested = myenv.default_amount_to_invest
    elif balance > 0 and balance < myenv.default_amount_to_invest:
      amount_invested = balance
      # balance -= amount_invested

  return amount_invested, balance


def get_symbol_info(symbol):
  '''
      return symbol_info, symbol_precision, step_size, tick_size
  '''
  symbol_info = loop.run_until_complete(get_client().get_symbol_info(symbol=symbol))
  symbol_precision = int(symbol_info['baseAssetPrecision'])
  quote_precision = int(symbol_info['quoteAssetPrecision'])
  for filter in symbol_info['filters']:
    if filter['filterType'] == 'LOT_SIZE':
      # stepSize defines the intervals that a quantity/icebergQty can be increased/decreased by
      step_size = float(filter['stepSize'])
    if filter['filterType'] == 'PRICE_FILTER':
      # tickSize defines the intervals that a price/stopPrice can be increased/decreased by; disabled on tickSize == 0
      tick_size = float(filter['tickSize'])

  quantity_precision = get_precision(step_size)
  price_precision = get_precision(tick_size)

  symbol_info['step_size'] = step_size
  symbol_info['quantity_precision'] = quantity_precision
  symbol_info['tick_size'] = tick_size
  symbol_info['price_precision'] = price_precision
  symbol_info['symbol_precision'] = symbol_precision

  return symbol_info, symbol_precision, quote_precision, quantity_precision, price_precision, step_size, tick_size


def calc_take_profit_stop_loss(strategy, actual_value: float, margin: float, stop_loss_multiplier=myenv.stop_loss_multiplier):
  take_profit_value = 0.0
  stop_loss_value = 0.0
  if strategy.startswith('SHORT'):  # Short
    take_profit_value = actual_value * (1 - margin / 100)
    stop_loss_value = actual_value * (1 + (margin * stop_loss_multiplier) / 100)
  elif strategy.startswith('LONG'):  # Long
    take_profit_value = actual_value * (1 + margin / 100)
    stop_loss_value = actual_value * (1 - (margin * stop_loss_multiplier) / 100)
  return take_profit_value, stop_loss_value


def get_params_operation(operation_date, symbol: str, interval: str, operation: str, target_margin: float, amount_invested: float, take_profit: float, stop_loss: float, purchase_price: float, rsi: float, sell_price: float,
                         profit_and_loss: float, margin_operation: float, strategy: str, balance: float, symbol_precision: int, quote_precision: int, quantity_precision: int, price_precision: int, step_size: float, tick_size: float):
  params_operation = {'operation_date': datetime.fromtimestamp(int(operation_date.astype(np.int64)) / 1000000000),
                      'symbol': symbol,
                      'interval': interval,
                      'operation': operation,
                      'target_margin': target_margin,
                      'amount_invested': amount_invested,
                      'take_profit': take_profit,
                      'stop_loss': stop_loss,
                      'purchase_price': purchase_price,
                      'sell_price': sell_price,
                      'pnl': profit_and_loss,
                      'rsi': rsi,
                      'margin_operation': margin_operation,
                      'strategy': strategy,
                      'balance': balance,
                      'symbol_precision': symbol_precision,
                      'price_precision': price_precision,
                      'tick_size': tick_size,
                      'step_size': step_size,
                      'quantity_precision': quantity_precision,
                      'quote_precision': quote_precision,
                      }
  return params_operation


def status_order_buy(symbol, interval):
  res_is_buying = False
  id = f'{symbol}_{interval}_buy'
  purchased_price = 0.0
  executed_qty = 0.0
  amount_invested = 0.0
  try:
    order = loop.run_until_complete(get_client().get_order(symbol=symbol, origClientOrderId=id, recvWindow=myenv.recv_window))
    res_is_buying = order['status'] in [Client.ORDER_STATUS_NEW, Client.ORDER_STATUS_PARTIALLY_FILLED]
    purchased_price = float(order['price'])
    executed_qty = float(order['executedQty'])
    amount_invested = purchased_price * executed_qty
  except Exception as e:
    log.exception(f'status_order_buy - ERROR: {e}')
    sm.send_status_to_telegram(f'{symbol}_{interval} - status_order_buy - ERROR: {e}')
  return res_is_buying, order, purchased_price, executed_qty, amount_invested


def get_asset_balance(asset=myenv.asset_balance_currency, quantity_precision: int = 2):
  filled_asset_balance = loop.run_until_complete(get_client().get_asset_balance(asset, recvWindow=myenv.recv_window))
  int_quantity = filled_asset_balance['free'].split('.')[0]
  frac_quantity = filled_asset_balance['free'].split('.')[1][:quantity_precision]
  quantity = float(int_quantity + '.' + frac_quantity)
  return quantity


def register_oco_sell(params):
  log.warn(f'Trying to register order_oco_sell: Params> {params}')

  symbol = params['symbol']
  interval = params['interval']

  limit_client_order_id = f'{symbol}_{interval}_limit'
  stop_client_order_id = f'{symbol}_{interval}_stop'
  price_precision = params['price_precision']
  quantity_precision = params['quantity_precision']
  take_profit = round(params['take_profit'], price_precision)
  stop_loss_trigger = round(params['stop_loss'], price_precision)
  stop_loss_target = round(stop_loss_trigger * 0.95, price_precision)

  _quantity = get_asset_balance(symbol.split('USDT')[0], quantity_precision)
  if _quantity > round(params['quantity'] * 1.05, quantity_precision):  # Sell 5% more quantity if total quantity of asset is more than
    quantity = round(params['quantity'] * 1.05, quantity_precision)
  elif _quantity >= round(params['quantity'], quantity_precision):  # Sell exactly quantity buyed
    quantity = round(params['quantity'], quantity_precision)
  else:
    quantity = _quantity  # Sell all quantity of asset

  oco_params = {}
  oco_params['symbol'] = params['symbol']
  oco_params['quantity'] = quantity
  oco_params['price'] = str(take_profit)
  oco_params['stopPrice'] = str(stop_loss_trigger)
  oco_params['stopLimitPrice'] = str(stop_loss_target)
  oco_params['stopLimitTimeInForce'] = 'GTC'
  oco_params['limitClientOrderId'] = limit_client_order_id
  oco_params['stopClientOrderId'] = stop_client_order_id
  oco_params['recvWindow'] = myenv.recv_window

  info_msg = f'ORDER SELL: {symbol}_{interval} - oco_params: {oco_params} - price_precision: {price_precision} - quantity_precision: {quantity_precision}'
  log.warn(info_msg)
  # sm.send_to_telegram(info_msg)

  oder_oco_sell_id = loop.run_until_complete(get_client().order_oco_sell(**oco_params))
  sm.send_status_to_telegram(info_msg + f' - oder_oco_sell_id: {oder_oco_sell_id}')
  log.warn(f'oder_oco_sell_id: {oder_oco_sell_id}')
  return oder_oco_sell_id


def register_operation(params):
  status, order_buy_id, order_oco_id = None, None, None
  try:
    log.warn(f'Trying to register order_limit_buy: Params> {params}')

    symbol = params['symbol']
    interval = params['interval']
    new_client_order_id = f'{symbol}_{interval}_buy'
    quantity_precision = params['quantity_precision']
    price_precision = params['price_precision']
    amount_invested = params['amount_invested']

    price_order = round(params['purchase_price'], price_precision)  # get_client().get_symbol_ticker(symbol=params['symbol'])
    params['purchase_price'] = price_order
    quantity = round(amount_invested / price_order, quantity_precision)
    params['quantity'] = quantity

    order_params = {}
    order_params['symbol'] = symbol
    order_params['quantity'] = quantity
    order_params['price'] = str(price_order)
    order_params['newClientOrderId'] = new_client_order_id
    order_params['recvWindow'] = myenv.recv_window

    order_buy_id = loop.run_until_complete(get_client().order_limit_buy(**order_params))

    info_msg = f'ORDER BUY: {order_params}'
    log.warn(info_msg)
    sm.send_status_to_telegram(info_msg + f'order_buy_id: {order_buy_id}')
    log.warn(f'order_buy_id: {order_buy_id}')

    purchase_attemps = 0
    is_buying, order_buy_id, _, _, _ = status_order_buy(params["symbol"], params["interval"])
    status = order_buy_id['status']
    while is_buying:
      if purchase_attemps > myenv.max_purchase_attemps:
        if status == Client.ORDER_STATUS_NEW:  # Can't buy after max_purchase_attemps, than cancel
          loop.run_until_complete(get_client().cancel_order(symbol=params['symbol'], origClientOrderId=new_client_order_id, recvWindow=myenv.recv_window))
          err_msg = f'Can\'t buy {params["symbol"]} after {myenv.max_purchase_attemps} attemps'
          log.error(err_msg)
          sm.send_status_to_telegram(f'[ERROR]: {symbol}_{interval}: {err_msg}')
          return status, None, None
        elif status == Client.ORDER_STATUS_PARTIALLY_FILLED:  # Partially filled, than try sell quantity partially filled
          msg = f'BUYING OrderId: {order_buy_id["orderId"]} Partially filled, than try sell quantity partially filled'
          log.warn(msg)
          sm.send_status_to_telegram(f'[WARNING]: {symbol}_{interval}: {msg}')
          break
      purchase_attemps += 1
      time.sleep(1)
      is_buying, order_buy_id, _, _, _ = status_order_buy(params["symbol"], params["interval"])
      status = order_buy_id['status']

    order_oco_id = register_oco_sell(params)
  except Exception as e:
    log.exception(e)
    sm.send_status_to_telegram(f'[ERROR] register_operation: {symbol}_{interval}: {e}')
    traceback.print_stack()

  return status, order_buy_id, order_oco_id


def status_order_limit(symbol, interval):
  id_limit = f'{symbol}_{interval}_limit'

  order = None
  res_is_purchased = False
  take_profit = 0.0
  try:
    order = loop.run_until_complete(get_client().get_order(symbol=symbol, origClientOrderId=id_limit, recvWindow=myenv.recv_window))
    res_is_purchased = order['status'] in [Client.ORDER_STATUS_NEW, Client.ORDER_STATUS_PARTIALLY_FILLED]
    take_profit = float(order['price'])
  except BinanceAPIException as e:
    if e.code != -2013:
      log.exception(f'status_order_limit - ERROR: {e}')
      sm.send_status_to_telegram(f'{symbol}_{interval} - status_order_limit - ERROR: {e}')
  except Exception as e:
    log.exception(f'status_order_limit - ERROR: {e}')
    sm.send_status_to_telegram(f'{symbol}_{interval} - status_order_limit - ERROR: {e}')

  return res_is_purchased, order, take_profit


def status_order_stop(symbol, interval):
  id_stop = f'{symbol}_{interval}_stop'

  order = None
  res_is_purchased = False
  stop_loss = 0.0
  try:
    order = loop.run_until_complete(get_client().get_order(symbol=symbol, origClientOrderId=id_stop, recvWindow=myenv.recv_window))
    res_is_purchased = order['status'] in [Client.ORDER_STATUS_NEW, Client.ORDER_STATUS_PARTIALLY_FILLED]
    stop_loss = float(order['stopPrice'])
  except Exception as e:
    log.exception(f'status_order_stop - ERROR: {e}')
    sm.send_status_to_telegram(f'{symbol}_{interval} - status_order_stop - ERROR: {e}')

  return res_is_purchased, order, stop_loss


def format_date(date):
  result = ''
  _format = '%Y-%m-%d %H:%M:%S'
  if date is not None:
    result = f'{date}'
    if isinstance(date, np.datetime64):
      result = pd.to_datetime(date, unit='ms').strftime(_format)
    elif isinstance(date, datetime):
      result = date.strftime(_format)

  return result
