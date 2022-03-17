#!/usr/bin/env python

# import numpy as np
# import os
import argparse
import dask
import datetime
import fsspec
import pandas as pd
import rechunker
import time
import xarray as xr
import zarr

from dask.distributed import Client


def build_filelist(num_days, c_start, wrf_dir):
    job_files = []

    for dd in range(num_days):
        cdate = c_start + datetime.timedelta(days=dd)

        wy_dir = f'WY{cdate.year}'
        if cdate >= datetime.datetime(cdate.year, 10, 1):
            wy_dir = f'WY{cdate.year+1}'

        for hh in range(24):
            fdate = cdate + datetime.timedelta(hours=hh)

            file_pat = f'{wrf_dir}/{wy_dir}/wrf2d_d01_{fdate.strftime("%Y-%m-%d_%H:%M:%S")}'
            job_files.append(file_pat)
    return job_files


def read_metadata(filename):
    # Read the metadata information file
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
    ds = ds.rename(rename_dims)
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


def rechunker_wrapper(source_store, target_store, temp_store, chunks=None,
                      mem=None, consolidated=False, verbose=True):
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
                if chunks[di] > len(ds_chunk[di]):
                    group_chunks[var].append(len(ds_chunk[di]))
                else:
                    group_chunks[var].append(chunks[di])

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


def main():
    parser = argparse.ArgumentParser(description='Create cloud-optimized zarr files from WRF CONUS404')
    parser.add_argument('-i', '--index', help='Index to process', required=True)

    args = parser.parse_args()

    base_dir = '/caldera/projects/usgs/water/wbeep/conus404_work/'
    wrf_dir = '/caldera/projects/usgs/water/impd/wrf-conus404/kyoko/wrfout_post'
    # tmp_dir = '/dev/shm'

    const_file = f'{base_dir}/wrf_constants_conus404_final.nc'
    metadata_file = f'{base_dir}/wrfout_metadata_w_std.csv'
    proc_vars_file = f'{base_dir}/wrf2d_vars_drb.csv'

    target_store = f'{base_dir}/test1/target'
    # temp_store = f'{base_dir}/test1/tmp'
    temp_store = '/dev/shm/tmp'
    # concat_store = f'{base_dir}/test1/conus404_2019'

    base_date = datetime.datetime(1979, 10, 1)
    # st_date = datetime.datetime(1979, 10, 1)
    # en_date = datetime.datetime(1982, 10, 1)

    num_days = 6
    delta = datetime.timedelta(days=num_days)

    # We can specify a chunk index and the start date is selected based on that
    # index_start = 66
    index_start = int(args.index)
    st_date = base_date + datetime.timedelta(days=num_days*index_start)
    en_date = st_date + delta - datetime.timedelta(days=1)
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

    # time_chunk = 144
    time_chunk = num_days * 24
    x_chunk = 175
    y_chunk = 175

    # Attributes that should be removed from all variables
    remove_attrs = ['FieldType', 'MemoryOrder', 'stagger', 'cell_methods']

    rename_dims = {'south_north': 'y', 'west_east': 'x',
                   'south_north_stag': 'y_stag', 'west_east_stag': 'x_stag',
                   'Time': 'time'}

    rename_vars = {'XLAT': 'lat', 'XLAT_U': 'lat_u', 'XLAT_V': 'lat_v',
                   'XLONG': 'lon', 'XLONG_U': 'lon_u', 'XLONG_V': 'lon_v'}

    # Read the metadata file for modifications to variable attributes
    var_metadata = read_metadata(metadata_file)

    # Add additional time attributes
    var_metadata['time'] = dict(axis='T', standard_name='time')

    # Start up the cluster
    client = Client(n_workers=8, threads_per_worker=1, memory_limit='24GB')
    # print(client)

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

    # Read variables to process
    df = pd.read_csv(proc_vars_file)

    fs = fsspec.filesystem('file')

    start = time.time()

    cnk_idx = index_start
    c_start = st_date

    while c_start < en_date:
        job_files = build_filelist(num_days, c_start, wrf_dir)
        tstore_dir = f'{target_store}_{cnk_idx:05d}'
        # num_time = len(job_files)

        # =============================================
        # Do some work here
        var_list = df['variable'].to_list()
        var_list.append('time')

        # rechunker requires empty tmp and target dirs
        try:
            fs.rm(temp_store, recursive=True)
        except:
            pass
        try:
            fs.rm(tstore_dir, recursive=True)
        except:
            pass

        time.sleep(3)  # wait for files to be removed (necessary? hack!)

        # ~~~~~~~~~~~~~~~~~~~~~~~~~
        # Open netcdf source files
        t1 = time.time()
        ds2d = xr.open_mfdataset(job_files, concat_dim='Time', combine='nested',
                                 parallel=True, coords="minimal", data_vars="minimal",
                                 compat='override', chunks={})

        if cnk_idx == 0:
            # Add the wrf constants during the first time chunk
            df_const = xr.open_dataset(const_file, chunks={})
            ds2d = ds2d.merge(df_const)
            ds2d = ds2d.rename(rename_vars)

            for vv in df_const.variables:
                if vv in rename_vars:
                    var_list.append(rename_vars[vv])
                else:
                    var_list.append(vv)
            df_const.close()

        ds2d = apply_metadata(ds2d, rename_dims, rename_vars, remove_attrs, var_metadata)
        print(f'    Open mfdataset: {time.time() - t1:0.3f} s')

        t1 = time.time()
        rechunker_wrapper(ds2d[var_list], target_store=tstore_dir, temp_store=temp_store,
                          mem=max_mem, consolidated=True, verbose=False,
                          chunks={'time': time_chunk,
                                  'y': y_chunk, 'x': x_chunk,
                                  'y_stag': y_chunk, 'x_stag': x_chunk})
        print(f'    rechunker: {time.time() - t1:0.3f} s')

        end = time.time()
        print(f'Chunk: {cnk_idx}, elapsed time: {(end - start) / 60.:0.3f}, {job_files[0]}')

        cnk_idx += 1
        c_start += delta

    client.close()
    
    # Clear out the temporary storage
    try:
        fs.rm(temp_store, recursive=True)
    except:
        pass

    if dask.config.get("temporary-directory") == '/dev/shm':
        try:
            fs.rm(f'/dev/shm/dask-worker-space', recursive=True)
        except:
            pass


if __name__ == '__main__':
    main()
