This is the README file written by the DSI S24 Fermi-GNN group (Setu Loomba, Ya-Wei Tsai, Aarman Pannu, Mathias Davila, Yufei Fan).
### Environment Setup

Make sure to be at your home directory on the cluster (e.g. /home/username).

1. Installing dependencies with Anaconda Client

    numl-dsi environment contains pytorch packages dependenceis for nugraph library.
    ```
    conda install -y anaconda-client
    conda env create numl/numl-dsi
    ```
2. Installing NuGraph in editable mode

    this allows you to access Fermilab researchers' latest update to nugraph library.
    ```
    git clone git@github.com:exatrkx/NuGraph.git
    conda activate numl-dsi
    pip install torch-geometric==2.5
    pip install --no-deps -e ./NuGraph
    ```

### Data Source
We will be using the MicroBoone dataset. This [link](https://microboone.fnal.gov/documents-publications/public-datasets/) contains more information on the data. The data file is located at /net/projects/fermi-gnn/CHEP2023.gnn.h5 -- make sure you have access to the data (you can check by running touch /net/projects/fermi-gnn/CHEP2023.gnn.h5).

### Train models in interactive session
Some lessons we learned: requesting 60G memory is enough, and GPU is necessary.
1. Request a compute node

```
srun --pty \
    --time=7:00:00 \
    --partition=general \
    --nodes=1 \
    --gres=gpu:1 \
    --cpus-per-gpu=8 \
    --mem-per-cpu=60G 
    bash
```

2. Run training script
```
scripts/train.py \
    --logdir <path-to-logs-folder> \
    --name dsi-example \
    --version semantic-filter-vertex \
    --data-path /net/projects/fermi-gnn/CHEP2023.gnn.h5 \
    --semantic \
    --filter \
    --vertex
```

### Train models with scripts
Edit train_batch_dsi.sh accordingly, then:

Submit the following command in terminal. Edit --logdir, --name and --version if necessary.
```
sbatch /home/username/NuGraph/scripts/train_batch_dsi.sh --data-path /net/projects/fermi-gnn/CHEP2023.gnn.h5 --logdir <path-to-logs-folder>  --name <name> --version <version-name> --filter --semantic --vertex
```


### Compare models with Tensorboard
1. Insert random numbers for XXXX which you think no one else will use, and run from terminal (numl-dsi should be activated):
```
tensorboard --port XXXX --bind_all --logdir <path-to-logs-folder> --samples_per_plugin images=200
```

2. Copy and paste the created link into a web browser
