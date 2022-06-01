#!/usr/bin/env python

import numpy as np
import os
import argparse
import dask
import datetime
import fsspec
# import numpy as np
# import pandas as pd
import rechunker
import time
import xarray as xr
import zarr

from typing import Dict, Optional, Union
from dask.distributed import Client


def teten_rh(qv: Union[float, xr.Dataset, xr.DataArray],
             pres: Union[float, xr.Dataset, xr.DataArray],
             temp: Union[float, xr.Dataset, xr.DataArray]):
    """Compute relative humidity using Teten's formula

    :param qv: Water vapor mixing ratio [kg kg-1]
    :param pres: Surface pressure [Pa]
    :param temp: Temperature [K]
    """
    # Teten's eqn
    # es0 = 6.113  # Saturation vapor pressure reference value; [hPa]
    # es0 *= 100   # [Pa]

    # epsilon = 0.622  # Rd / Rv; []

    # temp_c = temp - 273.15   # [C]

    # Vapor pressure
    e = compute_vp(qv, pres)
    # e = (qv * pres) / (epsilon + qv)   # [Pa]

    # Saturation vapor pressure
    es = teten_saturation_vp(temp)
    # es = es0 * np.exp(17.269 * temp_c / (temp_c + 237.3))   # [Pa]
    # es = es0 * math.exp((17.269 * (temp - 273.15)) / (temp - 35.86))   # [Pa]
    rh = 100.0 * (e / es)   # 0-100%

    return rh


def teten_saturation_vp(temperature: Union[float, xr.Dataset, xr.DataArray]):
    """Saturation vapor pressure from temperature

    :param temperature: Temperature [K]
    """
    # Teten's eqn
    es0 = 6.113  # Saturation vapor pressure reference value; [hPa]
    es0 *= 100   # [Pa]

    temp_c = temperature - 273.15   # [C]

    # Saturation vapor pressure
    es = es0 * np.exp(17.269 * temp_c / (temp_c + 237.3))   # [Pa]
    return es


def magnus_sat_vp(temp):
    # Magnus saturation vapor pressure formula
    # Relative error < 0.4% over -40C <= t <= 50C
    # Lawrence (2005), eqn 6
    c1 = 610.94   # [Pa]
    a1 = 17.625
    b1 = 243.04   # [C]

    temp_c = temp - 273.15
    es = c1 * np.exp(a1 * temp_c / (b1 + temp_c))

    print(f'{es=}')
    return es


def compute_rh(vp_mixing_ratio, pressure, temperature):
    # saturation vapor pressure
    num1 = temperature - 273.15
    den1 = temperature - 29.65
    es = 6.112 * np.exp(17.67 * num1 / den1)   # [Pa]

    # saturation water vapor mixing ratio
    num2 = 0.622 * es
    den2 = 0.01 * pressure - 0.378 * es
    qvs = num2 / den2

    # Compute relative humidity
    sh = vp_mixing_ratio / qvs
    rh = 100 * np.maximum(np.minimum(sh, 1.0), 0.0)
    return rh


def compute_specific_humidity(vp_mixing_ratio: Union[float, xr.Dataset, xr.DataArray]):
    """Specific humdity from vapor pressure mixing ratio

    :param vp_mixing_ratio: Vapor pressure mixing ratio [kg kg-1]"""
    return vp_mixing_ratio / (1 + vp_mixing_ratio)


def compute_vp(vp_mixing_ratio: Union[float, xr.Dataset, xr.DataArray],
               pressure: Union[float, xr.Dataset, xr.DataArray]):
    """Water vapor pressure from mixing ratio and pressure

    :param vp_mixing_ratio: Vapor pressure mixing ratio [kg kg-1]
    :param pressure: Pressure [Pa]
    """
    epsilon = 0.622  # Rd / Rv; []

    e = vp_mixing_ratio * pressure / (epsilon + vp_mixing_ratio)
    return e


# def compute_saturation_vp(temperature: Union[float, xr.Dataset, xr.DataArray]):
#     """Saturation vapor pressure from temperature
#
#     :param temperature: Temperature [K]
#     """
#     # Compute saturation vapor pressure from T2
#
#     # equation from Milly's DRB spreadsheet
#     return 611 * np.exp(17.269 * (temperature - 273.15) / (temperature - 35.85))


def compute_dewpoint_temperature(temperature, vp, sat_vp):
    #  237.3 * X / ( 17.269 - X ) ;  where X = { ln ( E2 / ESAT2 ) + 17.269 * ( T2 - 273.15 ) / ( T2 - 35.85 ) }
    # equation from Milly's DRB spreadsheet
    x = np.log(vp / sat_vp) + 17.269 * (temperature - 273.15) / (temperature - 35.85)
    return 237.3 * x / (17.269 - x)


def compute_dewpoint_temperature_magnus(vp_mixing_ratio: Union[float, xr.Dataset, xr.DataArray],
                                        pressure: Union[float, xr.Dataset, xr.DataArray]):
    """Compute dewpoint temperature based on Magnus formula

    :param vp_mixing_ratio: Vapor pressure mixing ratio [kg kg-1]
    :param pressure: Pressure [Pa]
    """
    # Lawrence (2005), eqn 7
    c1 = 610.94   # [Pa]
    a1 = 17.625
    b1 = 243.04   # [C]

    # Vapor pressure
    e = compute_vp(vp_mixing_ratio, pressure)

    # Dewpoint temperature
    td = (b1 * np.log(e / c1)) / (a1 - np.log(e / c1)) + 273.15

    return td


def read_metadata(filename: str):
    """Read the metadata information file

    :param filename: Path to metadata file
    """
    fhdl = open(filename, 'r')   # , encoding='ascii')
    rawdata = fhdl.read().splitlines()
    fhdl.close()

    it = iter(rawdata)
    next(it)   # Skip header

    var_metadata = {}
    for row in it:
        flds = row.split('\t')
        var_metadata[flds[0]] = {}

        if len(flds[1]) > 0:
            var_metadata[flds[0]]['long_name'] = flds[1]

        if len(flds[3]) > 0:
            var_metadata[flds[0]]['integration_length'] = flds[3]
        # if len(flds[8]) > 0:
        #     var_metadata[flds[0]]['standard_name'] = flds[8]
    return var_metadata


def apply_metadata(ds, rename_dims, rename_vars, remove_attrs, var_metadata):
    avail_dims = ds.dims.keys()
    rename_dims_actual = {}

    # Only change dimensions that exist in dataset
    for kk, vv in rename_dims.items():
        if kk in avail_dims:
            rename_dims_actual[kk] = vv

    ds = ds.rename(rename_dims_actual)
    ds = ds.assign_coords({'time': ds.XTIME})

    # Modify the attributes
    for cvar in ds.variables:
        # Remove unneeded attributes, update the coordinates attribute
        for cattr in list(ds[cvar].attrs.keys()):
            if cattr in remove_attrs:
                del ds[cvar].attrs[cattr]

            if cattr == 'coordinates':
                # Change the coordinates attribute to new lat/lon naming
                orig_coords = ds[cvar].attrs[cattr]
                new_coords = []
                for xx in orig_coords.split(' '):
                    if xx not in rename_vars:
                        continue
                    new_coords.append(rename_vars[xx])
                ds[cvar].attrs[cattr] = ' '.join(new_coords)

        # Apply the new metadata
        if cvar in var_metadata:
            for kk, vv in var_metadata[cvar].items():
                ds[cvar].attrs[kk] = vv

    return ds


def rechunker_wrapper(source_store: Union[xr.Dataset, xr.DataArray], target_store: str, temp_store: str,
                      chunks: Optional[Dict[str, int]] = None, mem: Optional[str] = None,
                      consolidated: Optional[bool] = False, verbose: Optional[bool] = True):
    """Rechunk a given xarray dataset and store in the zarr format.

    :param source_store: xarray dataset or path to dataset to rechunk
    :param target_store: Path to store rechunked dataset to
    :param temp_store: Path to temporary storage used during the rechunk process
    :param chunks: Dictionary of chunks to use for dimensions
    :param mem: Maximum amount of memory available for rechunking
    :param consolidated: If true consolidates the metadata for the final zarr object
    :param verbose: If true output additional information
    """
    if isinstance(source_store, xr.Dataset):
        g = source_store  # trying to work directly with a dataset
        ds_chunk = g
    else:
        g = zarr.group(str(source_store))
        # get the correct shape from loading the store as xr.dataset and parse the chunks
        ds_chunk = xr.open_zarr(str(source_store))

    group_chunks = {}
    # newer tuple version that also takes into account when specified chunks are larger than the array
    for var in ds_chunk.variables:
        # Pick appropriate chunks from above, and default to full length chunks for
        # dimensions that are not in `chunks` above.
        group_chunks[var] = []
        for di in ds_chunk[var].dims:
            if di in chunks.keys():
                if chunks[str(di)] > len(ds_chunk[di]):
                    group_chunks[var].append(len(ds_chunk[di]))
                else:
                    group_chunks[var].append(chunks[str(di)])

            else:
                group_chunks[var].append(len(ds_chunk[di]))

        group_chunks[var] = tuple(group_chunks[var])

    if verbose:
        print(f"Rechunking to: {group_chunks}")
        print(f"mem:{mem}")

    rechunked = rechunker.rechunk(g, target_chunks=group_chunks, max_mem=mem,
                                  target_store=target_store, temp_store=temp_store)
    rechunked.execute(retries=10)

    if consolidated:
        if verbose:
            print('consolidating metadata')
        zarr.convenience.consolidate_metadata(target_store)

    if verbose:
        print('done')


def set_file_path(path1: str, path2: Optional[str] = None):
    """Helper function to check/set the full path to a file.

    :param path1: absolute or relative path to a file (must include filename)
    :param path2: optional path to use when path1 is a filename
    """

    # file_path = None

    if os.path.isfile(path1):
        # File exists, use the supplied path
        file_path = os.path.realpath(path1)
    else:
        # file does not exist
        if path2:
            file_path = os.path.realpath(f'{path2}/{path1}')

            if os.path.isfile(file_path):
                # File exists in path2 so append it to the path
                print(f'Using filepath, {file_path}')
            else:
                raise FileNotFoundError(f'File, {path1}, does not exist in {path2}')
        else:
            raise FileNotFoundError(f'File, {path1}, does not exist')

    return file_path


def set_target_path(path: str, base_dir: Optional[str] = None, verbose: Optional[bool] = False):
    if os.path.isdir(path):
        # We're good, use it
        new_path = os.path.realpath(path)
        if verbose:
            print(f'{new_path} exists.')
    else:
        # path is not a directory, does the parent directory exist?
        pdir = os.path.dirname(path)

        if pdir == '':
            # There is no parent directory, try using base_dir if it exists
            if base_dir:
                # create/use
                if not os.path.isdir(base_dir):
                    raise FileNotFoundError(f'Base directory, {base_dir}, does not exist')

                new_path = f'{base_dir}/{path}'

                if os.path.isdir(new_path):
                    if verbose:
                        print(f'Using existing target path, {new_path}')
                else:
                    os.mkdir(new_path)

                    if verbose:
                        print(f'Creating target relative to base directory, {new_path}')
            else:
                # No base_dir supplied; create target path in current directory
                new_path = os.path.realpath(path)
                os.mkdir(new_path)

                if verbose:
                    print(f'Target path, {new_path}, created')
        elif os.path.isdir(pdir):
            # Parent path exists we just need to create the child directory
            new_path = os.path.realpath(path)
            os.mkdir(new_path)

            if verbose:
                print(f'Parent, {pdir}, exists. Created {new_path} directory')
        else:
            # print(f'ERROR: Parent of target path does not exist.')
            raise FileNotFoundError(f'Parent, {pdir}, of target path, {path}, does not exist')

    return new_path


def main():
    parser = argparse.ArgumentParser(description='Create cloud-optimized zarr files from WRF CONUS404 model output files')
    parser.add_argument('-i', '--index', help='Index to process', type=int, required=True)
    parser.add_argument('-b', '--base_dir', help='Directory to work in', required=False, default=None)
    # parser.add_argument('-w', '--wrf_dir', help='Base directory for WRF model output files', required=True)
    # parser.add_argument('-c', '--constants_file', help='Path to WRF constants', required=False, default=None)
    # parser.add_argument('-v', '--vars_file', help='File containing list of variables to include in output',
    #                     required=True)
    parser.add_argument('-d', '--dst_dir', help='Location to store rechunked zarr files', required=True)
    # parser.add_argument('-m', '--metadata_file', help='File containing metadata to include in zarr files',
    #                     required=True)
    parser.add_argument('-s', '--src_zarr', help='Path to source zarr dataset', required=True)
    parser.add_argument('--step', help='Number of indices to process from start index', type=int, default=1)

    args = parser.parse_args()

    print(f'HOST: {os.environ.get("HOSTNAME")}')
    print(f'SLURMD_NODENAME: {os.environ.get("SLURMD_NODENAME")}')
    # if os.environ.get('HOSTNAME') == 'denali-login2':
    #     exit(-1)

    base_dir = os.path.realpath(args.base_dir)
    # wrf_dir = os.path.realpath(args.wrf_dir)

    # const_file = set_file_path(args.constants_file, base_dir)
    # metadata_file = set_file_path(args.metadata_file, base_dir)
    # proc_vars_file = set_file_path(args.vars_file, base_dir)
    target_store = f'{set_target_path(args.dst_dir, base_dir)}/target'
    zarr_store = f'{set_target_path(args.src_zarr, base_dir)}'

    print(f'{base_dir=}')
    # print(f'{wrf_dir=}')
    # print(f'{const_file=}')
    # print(f'{metadata_file=}')
    # print(f'{proc_vars_file=}')
    print(f'{target_store=}')
    print(f'{zarr_store=}')
    print('-'*60)

    temp_store = '/dev/shm/tmp'
    base_date = datetime.datetime(1979, 10, 1)
    num_days = 6
    delta = datetime.timedelta(days=num_days)

    # We specify a chunk index and the start date is selected based on that
    index_start = args.index
    index_span = args.step
    index_end = index_start + index_span

    st_date = base_date + datetime.timedelta(days=num_days * index_start)

    # NOTE: en_date changed from processing a single zarr chunk to processing
    #       all zarr chunks
    en_date = datetime.datetime(2020, 9, 30)
    # en_date = st_date + delta - datetime.timedelta(days=1)
    print(f'{index_start=}')

    print(f'{base_date=}')
    print(f'{st_date=}')
    print(f'{en_date=}')
    print(f'{num_days=}')
    print(f'{delta=}')

    # if st_date.month != base_date.month or st_date.day != base_date.day:
    if (st_date - base_date).days % num_days != 0:
        print(f'Start date must begin at the start of a {num_days}-day chunk')

    # index_start = int((st_date - base_date).days / num_days)
    print(f'{index_start=}')
    print('-'*60)

    time_chunk = num_days * 24
    x_chunk = 175
    y_chunk = 175

    # Attributes that should be removed from all variables
    # remove_attrs = ['FieldType', 'MemoryOrder', 'stagger', 'cell_methods']
    #
    # rename_dims = {'south_north': 'y', 'west_east': 'x',
    #                'south_north_stag': 'y_stag', 'west_east_stag': 'x_stag',
    #                'Time': 'time'}
    #
    # rename_vars = {'XLAT': 'lat', 'XLAT_U': 'lat_u', 'XLAT_V': 'lat_v',
    #                'XLONG': 'lon', 'XLONG_U': 'lon_u', 'XLONG_V': 'lon_v'}

    # Read the metadata file for modifications to variable attributes
    # var_metadata = read_metadata(metadata_file)

    # Add additional time attributes
    # var_metadata['time'] = dict(axis='T', standard_name='time')

    # Start up the cluster
    client = Client(n_workers=8, threads_per_worker=1, memory_limit='24GB')

    print(f'dask tmp directory: {dask.config.get("temporary-directory")}')

    # Max total memory in gigabytes for cluster
    total_mem = sum(vv['memory_limit'] for vv in client.scheduler_info()['workers'].values()) / 1024**3
    total_threads = sum(vv['nthreads'] for vv in client.scheduler_info()['workers'].values())
    print(f'Total memory: {total_mem:0.1f} GB')
    print(f'Number of threads: {total_threads}')

    # Maximum percentage of memory to use for rechunking per thread
    max_percent = 0.7

    max_mem = f'{total_mem / total_threads * max_percent:0.0f}GB'
    print(f'Maximum memory per thread for rechunking: {max_mem}')
    print('='*60)

    # Read variables to process
    # df = pd.read_csv(proc_vars_file)

    fs = fsspec.filesystem('file')

    start = time.time()

    # cnk_idx = index_start
    # c_start = st_date

    ds = xr.open_dataset(zarr_store, engine='zarr',
                         backend_kwargs=dict(consolidated=True), chunks={})

    # st_date = base_date + datetime.timedelta(days=num_days * index_start)
    # en_date = st_date + datetime.timedelta(days=num_days) - datetime.timedelta(hours=1)

    # st_idx = index_start * time_cnk
    # en_idx = (index_start + 1) * time_cnk

    for ii in range(index_start, index_end):
        t1 = time.time()

        if base_date + datetime.timedelta(days=num_days * ii) >= en_date:
            # No more dates left to process
            break

        c_start = ii * time_chunk
        c_end = (ii + 1) * time_chunk

        tstore_dir = f'{target_store}_{ii:05d}'

        # rechunker requires empty tmp and target dirs
        try:
            fs.rm(temp_store, recursive=True)
        except FileNotFoundError:
            pass

        try:
            fs.rm(tstore_dir, recursive=True)
        except FileNotFoundError:
            pass

        time.sleep(3)  # wait for files to be removed (necessary? hack!)

        ds2 = ds[['T2', 'Q2', 'PSFC']].isel(time=slice(c_start, c_end))

        ds2['RH2'] = teten_rh(ds2.Q2, ds2.PSFC, ds2.T2)
        ds2['SH2'] = compute_specific_humidity(ds2.Q2)
        ds2['E2'] = compute_vp(ds2.Q2, ds2.PSFC)
        ds2['ESAT2'] = teten_saturation_vp(ds2.T2)
        ds2['TD2'] = compute_dewpoint_temperature_magnus(ds2.Q2, ds2.PSFC)

        ds2.compute()
        end = time.time()
        print(f'Compute RH2, SH2, E2, ESAT2, TD2: {ii}, elapsed time: {end - t1:0.3f} s')

        # t1 = time.time()
        # ds2['TD2'] = compute_dewpoint_temperature(ds2.T2, ds2.E2, ds2.ESAT2)
        # ds2.compute()
        # end = time.time()
        # print(f'Compute TD2: {ii}, elapsed time: {end - t1:0.3f} s')

        var_list = ['time', 'RH2', 'SH2', 'E2', 'ESAT2', 'TD2']

        t1 = time.time()
        rechunker_wrapper(ds2[var_list], target_store=tstore_dir, temp_store=temp_store,
                          mem=max_mem, consolidated=True, verbose=False,
                          chunks={'time': time_chunk,
                                  'y': y_chunk, 'x': x_chunk})
        print(f'    rechunker: {time.time() - t1:0.3f} s')

        end = time.time()
        print(f'Chunk: {ii}, elapsed time: {(end - start) / 60.:0.3f}')

    # while c_start < en_date:
    #     # job_files = build_filelist(num_days, c_start, wrf_dir)
    #     tstore_dir = f'{target_store}_{cnk_idx:05d}'
    #     # num_time = len(job_files)
    #
    #     # slice('1979-10-01 00:00','1979-10-06 23:00')
    #     ds2 = ds[['T2', 'Q2', 'PSFC']].sel(time=slice(c_start, ))
    #     # =============================================
    #     # Do some work here
    #     # var_list = df['variable'].to_list()
    #     # var_list.append('time')
    #
    #     # rechunker requires empty tmp and target dirs
    #     try:
    #         fs.rm(temp_store, recursive=True)
    #     except:
    #         pass
    #     try:
    #         fs.rm(tstore_dir, recursive=True)
    #     except:
    #         pass
    #
    #     time.sleep(3)  # wait for files to be removed (necessary? hack!)
    #
    #     t1 = time.time()
    #     ds2['RH2'] = compute_rh(ds2.Q2, ds2.PSFC, ds2.T2)
    #     ds2['SH2'] = compute_specific_humidity(ds2.Q2)
    #     ds2['E2'] = compute_vp(ds2.Q2, ds2.PSFC)
    #     ds2['ESAT2'] = compute_saturation_vp(ds2.T2)
    #
    #     ds2.compute()
    #     end = time.time()
    #     print(f'Compute RH2, SH2, E2, ESAT2: {cnk_idx}, elapsed time: {end - t1:0.3f} s')
    #
    #     t1 = time.time()
    #     ds2['TD2'] = compute_dewpoint_temperature(ds2.T2, ds2.E2, ds2.ESAT2)
    #     ds2.compute()
    #     end = time.time()
    #     print(f'Compute RH2, SH2, E2, ESAT2: {cnk_idx}, elapsed time: {end - t1:0.3f} s')
    #
    #     var_list = ['time', 'RH2', 'SH2', 'E2', 'ESAT2']
    #
    #     t1 = time.time()
    #     rechunker_wrapper(ds2[var_list], target_store=tstore_dir, temp_store=temp_store,
    #                       mem=max_mem, consolidated=True, verbose=False,
    #                       chunks={'time': time_chunk,
    #                               'y': y_chunk, 'x': x_chunk})
    #     print(f'    rechunker: {time.time() - t1:0.3f} s')
    #
    #     end = time.time()
    #     print(f'Chunk: {cnk_idx}, elapsed time: {(end - start) / 60.:0.3f}')
    #
    #     cnk_idx += 1
    #     c_start += delta - datetime.timedelta(days=1)

    client.close()

    # Clear out the temporary storage
    try:
        fs.rm(temp_store, recursive=True)
    except FileNotFoundError:
        pass

    if dask.config.get("temporary-directory") == '/dev/shm':
        try:
            fs.rm(f'/dev/shm/dask-worker-space', recursive=True)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
