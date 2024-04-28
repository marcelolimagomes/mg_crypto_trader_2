import os
import logging

import src.utils as utils
import src.myenv as myenv

from multiprocessing import Process
from src.bot import Bot


class RunMultiBots:
  def __init__(self, params):
    self.params = params
    self.log = logging.getLogger()
    # Initialize logging
    if 'log_level' in params:
      self.log = utils.configure_log(log_level=params['log_level'])
    else:
      self.log = utils.configure_log(log_level=myenv.log_level)

  def run(self):
    symbols = utils.get_symbol_list()
    interval_list = self.params['interval_list']

    for symbol in symbols:
      for interval in interval_list:
        ix_symbol = f'{symbol}_{interval}'
        new_params = self.params.copy()
        new_params['symbol'] = symbol
        new_params['interval'] = interval

        robo = Bot(new_params)
        self.log.info(f'Running bot for {ix_symbol}')
        process = Process(target=robo.run, name=ix_symbol)
        process.start()
