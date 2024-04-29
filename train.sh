#!/bin/bash

eval "$(conda shell.bash hook)"

cd /home/marcelo/des/mg_crypto_trader_2/
conda activate mg 
python /home/marcelo/des/mg_crypto_trader_2/. -download-data -interval-list=1h,30m -verbose
python /home/marcelo/des/mg_crypto_trader_2/. -train -interval-list=1h,30m -verbose