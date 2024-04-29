#!/bin/bash

eval "$(conda shell.bash hook)"

cd /home/marcelo/des/mg_crypto_trader_2/
conda activate mg 
#python /home/marcelo/des/mg_crypto_trader_2/. -download-data -interval-list=1h,30m -log-level=INFO
python /home/marcelo/des/mg_crypto_trader_2/. -run-bots -interval-list=1h,30m -model-algorithm=et -log-level=INFO