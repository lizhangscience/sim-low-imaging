#!/bin/bash
#!

# wsclean -weight uniform -log-time -size 20480 20480 -scale 1.7578125asec -niter  20000 -mgain 0.8 -auto-threshold 3 -pol xx ../GLEAM_A-team_EoR0_no_errors.ms

cp ../clean_ms.py .
python ./clean_ms.py --ngroup 1 --nworkers 8 --weighting uniform --context wprojection \
--mode pipeline --niter 1000 --nmajor 3 --fractional_threshold 0.2 --threshold 0.01 \
--amplitude_loss 0.25 --deconvolve_facets 8 --deconvolve_overlap 32 \
--msname /mnt/storage-ssd/tim/Code/sim-low-imaging/data/EoR0_20deg_24.MS \
--time_coal 0.0 --frequency_coal 0.0 --memory 128 --channels 131 132 --window_shape no_edge --window_edge 16 \
--use_serial_invert False --use_serial_predict False --plot False --fov 1.4 --single False | tee clean_ms.log