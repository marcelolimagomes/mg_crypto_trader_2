from src.run_multi_bots import RunMultiBots

import src.utils as utils
import src.myenv as myenv
import src.train as train
import os
import traceback

import sys
import logging


def main(args):
  print(f'args: {args}')
  interval_list = ['1h']
  log_level = logging.DEBUG
  auto_start_date = False
  start_date = '2010-01-01'
  log = None
  tail = -1
  model_algorithm = 'et'

  for arg in args:
    if (arg.startswith('-log-level=DEBUG')):
      log_level = logging.DEBUG
    if (arg.startswith('-log-level=WARNING')):
      log_level = logging.WARNING
    if (arg.startswith('-log-level=INFO')):
      log_level = logging.INFO
    if (arg.startswith('-log-level=ERROR')):
      log_level = logging.ERROR
    if (arg.startswith('-interval-list=')):
      aux = arg.split('=')[1]
      interval_list = aux.split(',')
    if (arg.startswith('-start-date=')):
      start_date = arg.split('=')[1]
    if (arg.startswith('-tail=')):
      tail = int(arg.split('=')[1])
    if (arg.startswith('-model-algorithm=')):
      model_algorithm = arg.split('=')[1]

  verbose = '-verbose' in args

  log = utils.configure_log(log_level=log_level)
  if '-download-data' in args:
    try:
      for interval in interval_list:
        if auto_start_date:
          _, aux_date = utils.get_start_date_for_interval(interval)
          start_date = aux_date.strftime("%Y-%m-%d")
        log.info(f'Starting download data, in interval ({interval}) auto-start-date: {auto_start_date} - start-date: {start_date} tail: {tail} for all Symbols in database...')
        utils.download_data(save_database=True, parse_dates=False, tail=tail, interval=interval, start_date=start_date)
    except Exception as e:
      log.exception(e)
      traceback.print_stack()
      sys.exit(0)
    finally:
      sys.exit(0)

  if '-train' in args:
    try:
      for interval in interval_list:
        log.info(f'Starting train, in interval ({interval}) for all Symbols in database...')
        train.main(interval_list, log_level)
    except Exception as e:
      log.exception(e)
      traceback.print_stack()
      sys.exit(0)
    finally:
      sys.exit(0)

  if '-run-bots' in args:
    try:
      log.info(f'Starting run bots, in interval ({interval_list}), model_algorithm: {model_algorithm} for all Symbols in database...')
      bots = RunMultiBots({
        'interval_list': interval_list,
        'log_level': log_level,
        'model_algorithm': model_algorithm,
        'verbose': verbose,
        'args': args,
      })
      bots.run()
    except Exception as e:
      log.exception(e)
      traceback.print_stack()


if __name__ == '__main__':
  main(sys.argv[1:])
