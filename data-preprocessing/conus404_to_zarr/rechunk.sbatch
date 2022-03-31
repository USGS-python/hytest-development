#!/bin/bash
#SBATCH -J rechunk
#SBATCH -t 00:20:00
#SBATCH -o %j-rechunk.out
#SBATCH -p workq
#SBATCH -A wbeep
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
# #SBATCH --array=0-2495%50

export PATH="$PATH:$HOME/miniconda3/bin"

source activate pangeo

python /caldera/projects/usgs/water/wbeep/conus404_work/conus404_rechunk_ja.py -i $SLURM_ARRAY_TASK_ID

