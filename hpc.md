# Getting started with HyTest with on-prem HPC 

This tutorial covers how to set up and use the HyTest Framework on USGS High Performance Computing (HPC) systems:

1.  Installing [conda](https://conda.io/docs/) and creating a custom Hytest conda environment 
2.  Configuring [Jupyter](https://jupyter.org/)
3.  Launching [Dask](https://dask.pydata.org/) with a job scheduler
4.  Launching a [Jupyter](https://jupyter.org/) server 
5.  Connecting to [Jupyter](https://jupyter.org/) and the
    [Dask](https://dask.pydata.org/) dashboard from your personal
    computer

This document assumes that you already have an
access to Denali and Tallgrass and are comfortable using the command
line. 

## Installing a software environment

First log into Denali or Tallgrass.  You will need to be on doi.net to assess these systems, so if you are remote you will need to use the VPN (Pulse Secure) or login to an AWS Workspace machine (if you have one).  

After logging in, request interactive access to a compute node so that you are not working on the main node. You can do this using a command like:
```bash
#!/bin/bash
salloc -A woodshole -t 02:00:00 -N 1 srun --pty bash
```
which requests a node for 2 hours using the "woodshole" account.  You need to use your account name and adjust the time accordingly. 

Next install the Conda package managment system to allow generation of self-contained Python environments without involving system admins. We will install "Mamba", which is a drop drop-in replacement for "conda" providing a fast, efficient and license-free way to run conda commands.  Copy and paste these lines to the terminal:

```bash
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Mambaforge-$(uname)-$(uname -m).sh"

bash Mambaforge-$(uname)-$(uname -m).sh
```
Answer "yes" to accept the license agreement, and "yes" when it asks if you want the script to run `conda init`. 

Now update your conda package manager with packages from the conda-forge channel:

```bash
conda config --add channels conda-forge --force 
mamba update --all
```
This will create a ``./condarc`` in your home
directory with the `conda-forge` channel setting. 

Now let's create a new conda environment for our HyTest work:
```bash
mamba create -n hytest -c conda-forge \
      python dask jupyterlab dask-jobqueue ipywidgets \
      xarray zarr numcodecs hvplot geoviews datashader  \
      jupyter-server-proxy widgetsnbextension dask-labextension
```
*Note: you can add additional conda packages you need to this list.  Packages available through conda-forge can be explored at https://anaconda.org. 

Activate this environment:
```bash
conda activate hytest
```
Your prompt should now look something like this (note the "hytest" environment name):
```
(hytest) $
```

And if you ask where your Python command lives, it should direct you to somewhere in your home directory:
```
(hytest) $ which python
$HOME/Miniforge3/envs/hytest/bin/python
```
## Configure Jupyter

Jupyter notebook servers include a password for security. First we generate the Jupyter config file then set a password:
```
jupyter server --generate-config
jupyter server password
```
This creates the file `~/.jupyter/jupyter_server_config.py`. 

Finally, we configure dask\'s dashboard to forward through
Jupyter.  Add this line to your `~/.bashrc` file:
```
export DASK_DISTRIBUTED__DASHBOARD__LINK="/proxy/8787/status"
```
------------------------------------------------------------------------

From here, we have two options. Option 1 will start a Jupyter Notebook server and manage dask using the
[dask-jobqueue](http://dask-jobqueue.readthedocs.io) package. Option 2 will start a dask cluster using [dask-mpi]{.title-ref} and will run a Jupyter server as part of the dask cluster. We generally recommend starting with Option 1, especially if you will be working interactively, unless you have a reason for managing the job submission scripts on your
own. Users that will be using dask in batch-style workflows may prefer Option 2.

## Deploy Option 1: Jupyter + dask-jobqueue

### Start a Jupyter Notebook Server

Now that we have Jupyter configured, we can start a notebook server on our interactive compute node.  We can use a script like this: 

```bash
(pangeo) rsignell@nid00243:~> more ~/bin/start_jupyter

#!/bin/bash
source activate hytest
cd $HOME/HyTest/Projects
HOST=`hostname`
JPORT=$(shuf -i 8400-9400 -n 1)
echo ""
echo ""
echo "Step 1: Wait until this script says the Jupyter server"
echo "        has started. "
echo ""
echo "Step 2: Copy this ssh command into a terminal on your"
echo "        local computer:"
echo ""
echo "        ssh -N -L 8889:$HOST:$JPORT  USER@$SLURM_CLUSTER_NAME.cr.usgs.gov"
echo ""
echo "Step 3: Browse to https://localhost:8889 on your local computer"
echo ""
echo ""
jupyter lab --no-browser --ip=$HOST --port=$JPORT
```
Then follow the Steps 1,2,3 printed out by the script to get connected.

### Launch Dask with dask-jobqueue

Most HPC systems use a job-scheduling system to manage job submissions
and executions among many users. The
[dask-jobqueue](http://dask-jobqueue.readthedocs.io) package is designed to help dask interface with these job queuing systems. Usage is quite simple and can be done from within your Jupyter Notebook:

```python
from dask_jobqueue import SLURMCluster

if os.environ['SLURM_CLUSTER_NAME']=='tallgrass':
    cluster = SLURMCluster(processes=1,cores=1, 
        memory='10GB', interface='ib0',
        project='woodshole', walltime='04:00:00',
        job_extra={'hint': 'multithread', 
        'exclusive':'user'})

cluster.scale(18)

from dask.distributed import Client
client = Client(cluster)
```

The `scale()` method submits a batch of jobs to the SLURM job
queue system.  Depending on how busy the job queue is,
it can take a few minutes for workers to join your cluster. You can usually check the status of your queued jobs using a command line
utility like [squeue -u $USER. You can also check the status of your cluster from inside your Jupyter session:

``` python
print(client)
```

For more examples of how to use
[dask-jobqueue](http://dask-jobqueue.readthedocs.io), refer to the
[package documentation](http://dask-jobqueue.readthedocs.io).


## Further Reading

 -   [Deploying Dask on HPC](http://dask.pydata.org/en/latest/setup/hpc.html)
 -   [Configuring and Deploying Jupyter Servers](http://jupyter-notebook.readthedocs.io/en/stable/index.html)

