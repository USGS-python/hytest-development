# Getting started with HyTest with on-prem HPC 

This tutorial covers how to set up an environment to run the HyTest Framework 
on High Performance Computing (HPC) systems. In particular it covers the
following:

1.  Install [conda](https://conda.io/docs/) and creating an environment
2.  Configure [Jupyter](https://jupyter.org/)
3.  Launch [Dask](https://dask.pydata.org/) with a job scheduler
4.  Launch a [Jupyter](https://jupyter.org/) server for your job
5.  Connect to [Jupyter](https://jupyter.org/) and the
    [Dask](https://dask.pydata.org/) dashboard from your personal
    computer

Although the examples on this page were developed using NCAR\'s
[Cheyenne](https://www2.cisl.ucar.edu/resources/computational-systems/cheyenne)
super computer, the concepts here should be generally applicable to
typical HPC systems. This document assumes that you already have an
access to an HPC like Cheyenne, and are comfortable using the command
line. It may be necessary to work with your system administrators to
properly configure these tools for your machine.

You should log into your HPC system now.

## Installing a software environment

After you have logged into your HPC system, download and install
Miniforge:

```bash
url=https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh  
curl $url -o Miniforge.sh
sh Miniforge.sh
export PATH=$HOME/Miniforge3/bin:$PATH
```

This contains a self-contained Python environment that we can manipulate
safely without requiring the involvement of IT. It also allows you to
create isolated software environments so that we can experiment in the
future safely.

Before creating your environment, update your conda package manager with
packages from the conda-forge channel instead of the default channel and
install Mamba, which works like conda but is written in C++ and
therefore creates environments faster.

```bash

 conda config --add channels conda-forge --force 
 conda config --remove channels defaults --force 
 conda install mamba -y 
 mamba update --all
```
::: note

Depending if you chose to initialize Miniforge in your `~/.bashrc` at
the end of the installation, this new conda update will activate a
`(base)` environment by default. If you wish to prevent conda from
activating the `(base)` environment at shell initialization:
```bash
conda config --set auto_activate_base false
```
This will create a ``./condarc`` in your home
directory with this setting the first time you run it. 

:::

Create a new conda environment for our HyTest work:
```bash
mamba create -n hytest -c conda-forge \
      python dask jupyterlab dask-jobqueue ipywidgets \
      xarray zarr numcodecs hvplot geoviews datashader  \
      jupyter-server-proxy widgetsnbextension dask-labextension

::: note

Depending on your application, you may choose to add additional conda
packages to this list.

:::

Activate this environment (and note that with Jupyterlab version 3,
extensions no longer need to be added after environment creation):
```bash
conda activate hytest
```
Your prompt should now look something like this (note the "hytest"
environment name):
```
(hytest) $
```

And if you ask where your Python command lives, it should direct you to
somewhere in your home directory:
```
    (hytest) $ which python
    $HOME/Miniforge3/envs/hytest/bin/python
```
## Configure Jupyter

(If you don\'t plan to use Jupyter notebooks then you can safely skip
this section.)

Jupyter notebook servers include a password for security. First we
generate the Jupyter config file then set a password:
```
    jupyter server --generate-config
    jupyter server password
```
This created a file in `~/.jupyter/jupyter_server_config.py`. For
security reasons, we recommend making sure your
`jupyter_server_config.py` is readable only by you. For more information
on this and other methods for securing Jupyter, check out [Securing a
notebook
server](http://jupyter-notebook.readthedocs.io/en/stable/public_server.html#securing-a-notebook-server)
in the Jupyter documentation.
```
    chmod 400 ~/.jupyter/jupyter_server_config.py
```
Finally, we may want to configure dask\'s dashboard to forward through
Jupyter.

Add this to your `~/.bashrc` file:
```
    export DASK_DISTRIBUTED__DASHBOARD__LINK="/proxy/8787/status"
```
------------------------------------------------------------------------

From here, we have two options. Option 1 will start a Jupyter Notebook
server and manage dask using the
[dask-jobqueue](http://dask-jobqueue.readthedocs.io) package. Option 2
will start a dask cluster using [dask-mpi]{.title-ref} and will run a
Jupyter server as part of the dask cluster. We generally recommend
starting with Option 1, especially if you will be working interactively,
unless you have a reason for managing the job submission scripts on your
own. Users that will be using dask in batch-style workflows may prefer
Option 2.

## Deploy Option 1: Jupyter + dask-jobqueue

### Start a Jupyter Notebook Server

Now that we have Jupyter configured, we can start a notebook server. In
many cases, your system administrators will want you to run this
notebook server in an interactive session on a compute node. This is not
universal rule, but it is one we\'ll follow for this tutorial.

In our case, the Cheyenne super computer uses the PBS job scheduler, so
typing:
```
    (hytest) $ qsub -I -A account -l select=1:ncpus=4 -l walltime=03:00:00 -q regular

This will get us an interactive job on the [regular]{.title-ref} queue
for three hours. You may not see the [hytest]{.title-ref} environment
anymore in your prompt, in this case, you will want to reactivate it.

    conda activate hytest

From here, we can start jupyter. The Cheyenne computer administrators
have developed a
[start-notebook](https://www2.cisl.ucar.edu/resources/computational-systems/cheyenne/software/jupyter-and-ipython#notebook)
utility that wraps the following steps into a single execution. You
should check with your system administrators to see if they have
something similar.

If not, you can easily create your own start_jupyter script. In the
script below, we choose a random port on the server (to reduce the
chance of conflict with another user), but we use port 8889 on the
client, as port 8888 is the default client port if you are running
Jupyter locally. We can also change to a starting directory:

    (hytest) $ more ~/bin/start_jupyter 
    cd /home/data/username
    JPORT=$(shuf -i 8400-9400 -n 1)
    echo ""
    echo ""
    echo "Step 1: Wait until this script says the Jupyter server"
    echo "        has started. "
    echo ""
    echo "Step 2: Copy this ssh command into a terminal on your"
    echo "        local computer:"
    echo ""
    echo "        ssh -N -L 8889:`hostname`:$JPORT $USER@my-hpc-cluster.edu"
    echo ""
    echo "Step 3: Browse to http://localhost:8889 on your local computer"
    echo ""
    echo ""
    sleep 2
    jupyter lab --no-browser --ip=`hostname` --port=$JPORT

Now we can launch the Jupyter server: :

    (hytest) $ ~/bin/start_jupyter

    Step 1:...
    Step 2:...
    Step 3:...
    ...

    [I 2021-04-06 06:33:57.962 ServerApp] Jupyter Server 1.5.1 is running at:
    [I 2021-04-06 06:33:57.962 ServerApp] http://pn009:8537/lab     
    [I 2021-04-06 06:33:57.963 ServerApp]  or http://127.0.0.1:8537/lab
    [I 2021-04-06 06:33:57.963 ServerApp] Use Control-C to stop this server and shut down all kernels (twice to skip confirmation).

Just follow the Steps 1,2,3 printed out by the script to get connected.

### Launch Dask with dask-jobqueue

Most HPC systems use a job-scheduling system to manage job submissions
and executions among many users. The
[dask-jobqueue](http://dask-jobqueue.readthedocs.io) package is designed
to help dask interface with these job queuing systems. Usage is quite
simple and can be done from within your Jupyter Notebook:

``` python
from dask_jobqueue import PBSCluster

cluster = PBSCluster(cores=36,
                     processes=18, memory="6GB",
                     project='UCLB0022',
                     queue='premium',
                     resource_spec='select=1:ncpus=36:mem=109G',
                     walltime='02:00:00')
cluster.scale(18)

from dask.distributed import Client
client = Client(cluster)
```

The [scale()]{.title-ref} method submits a batch of jobs to the job
queue system (in this case PBS). Depending on how busy the job queue is,
it can take a few minutes for workers to join your cluster. You can
usually check the status of your queued jobs using a command line
utility like [qstat]{.title-ref}. You can also check the status of your
cluster from inside your Jupyter session:

``` python
print(client)
```

For more examples of how to use
[dask-jobqueue](http://dask-jobqueue.readthedocs.io), refer to the
[package documentation](http://dask-jobqueue.readthedocs.io).


## Further Reading

 -   [Deploying Dask on HPC](http://dask.pydata.org/en/latest/setup/hpc.html)
 -   [Configuring and Deploying Jupyter Servers](http://jupyter-notebook.readthedocs.io/en/stable/index.html)

