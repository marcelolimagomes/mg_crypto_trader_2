#!/bin/bash

eval "$(conda shell.bash hook)"

cd /home/marcelo/des/mg_crypto_trader_2/
conda activate pycaret 
python /home/marcelo/des/mg_crypto_trader_2/. -download-data -interval-list=1h,30m -verbose

python . -run-bots -interval-list=1h,30m -model-algorithm=et -log-level=DEBUG