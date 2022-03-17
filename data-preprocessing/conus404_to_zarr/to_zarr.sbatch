#!/bin/bash
#SBATCH -J cat_zarr
#SBATCH -t 00:20:00
#SBATCH -o %j-to_zarr.out
#SBATCH -p workq
#SBATCH -A wbeep
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=40
#  #SBATCH --array=10-100:10

# STEP should match the stride in the --array argument
export STEP=10
export PATH="$PATH:$HOME/miniconda3/bin"

source activate pangeo

echo $SLURM_ARRAY_TASK_ID
python /caldera/projects/usgs/water/wbeep/conus404_work/conus404_to_zarr.py -i $SLURM_ARRAY_TASK_ID -s $STEP

