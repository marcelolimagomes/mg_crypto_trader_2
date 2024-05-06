import os
import logging

import src.utils as utils
import src.myenv as myenv
import src.send_message as sm

from multiprocessing import Process
from src.bot import Bot

import traceback
import time

class RunMultiBots:
  def __init__(self, params):
    self.params = params
    self.log = logging.getLogger("MAIN")
    # Initialize logging
    if 'log_level' in params:
      self.log = utils.configure_log(log_level=params['log_level'])
    else:
      self.log = utils.configure_log(log_level=myenv.log_level)

  def run(self):
    symbols = utils.get_symbol_list()
    interval_list = self.params['interval_list']

    plist = []
    for symbol in symbols:
      for interval in interval_list:
        ix_symbol = f'{symbol}_{interval}'
        new_params = self.params.copy()
        new_params['symbol'] = symbol
        new_params['interval'] = interval
        new_params['target_margin'] = myenv.stop_loss
        new_params['stop_loss_multiplier'] = myenv.stop_loss_multiplier
        new_params['step_rsi'] = myenv.step_rsi
        new_params['p_ema'] = myenv.p_ema

        self.log.info(f'Starting bot for {ix_symbol}')

        try:
          robo = Bot(new_params)
          process = Process(target=robo.run, name=ix_symbol)
          plist.append({'name': ix_symbol, 'params': new_params, 'process': process})
          process.start()

          sm.send_status_to_telegram(f'Starting bot for {ix_symbol}') 
        except Exception as e:
          self.log.exception(f'{ix_symbol} ERRO: {e}')
          traceback.print_stack()

    while True:
      try:
        for p in plist:
          self.log.info(f'Status process: {p["name"]} - {p["process"]}')
          #p['process'].join()
      except Exception as e:
        self.log.exception(f'ERRO: {e}')
      finally:    
        time.sleep(300)
