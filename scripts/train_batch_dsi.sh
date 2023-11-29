#!/bin/bash
#SBATCH --job-name=fermi2
#SBATCH --output=//net/projects/fermi-2/logs/%u/%A.out
#SBATCH --error=/net/projects/fermi-2/logs/%u/%A.err
#SBATCH --time=12:00:00
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:1
#SBATCH --constraint=a100
#SBATCH --mem-per-cpu=64G

#SBATCH --mail-type=ALL  # Mail events (NONE, BEGIN, END, FAIL, ALL)
#SBATCH --mail-user=jiheeyou@rcc.uchicago.edu  # mail notification for the job
#SBATCH --open-mode=append # So that outcomes are appended, not rewritten
#SBATCH --signal=SIGUSR1@90
#SBATCH --nodelist=i001
echo $SLURM_RESTART_COUNT

# Instructions:
# - start from the login node (fe01)
# - activate environment
# - cd to ~/NuGraph
# - modify params in train_batch_dsi.sh as needed
# - in command line, run: sbatch scripts/train_batch_dsi.sh

# Or to run interactively, request session with:
# srun -p general -t "12:00:00" --mem "64G" --cpus-per-task 2 --gres gpu:1 --constraint a100 --pty /bin/bash



################ CHANGE ################
# mlp features
vtx_mlp_features=64

# aggregator
vtx_aggr="lstm"

# lstm features
vtx_lstm_features=8

# set variables
epochs=80

lim_train_batches=1
lim_val_batches=1

# don't forget to also update the arguments of the python script call below: it should contain with (--logdir & --name) OR (--resume)
# ckpt="epoch=58-step=276887.ckpt"
#########################################


# make logdir under username
username=$USER
logdir="/net/projects/fermi-2/logs/${username}"
mkdir -p "$logdir"
echo $logdir


# set log_name with specified parameters
log_name="log_aggr_${vtx_aggr}_mlpfeats_${vtx_mlp_features}_lstmfeats_${vtx_lstm_features}"


# run training
srun python scripts/train.py \
                 --data-path /net/projects/fermi-2/CHEP2023.gnn.h5 \
                 --version ${log_name} \
                 --semantic \
                 --filter \
                 --vertex \
                 --vertex-aggr ${vtx_aggr} \
                 --vertex-lstm-feats ${vtx_lstm_features} \
                 --vertex-mlp-feats ${vtx_mlp_features} \
                 --epochs ${epochs} \
                 --logdir ${logdir} \
                 --name  "Vertex_Decoder_Search" \
                 --resume "${logdir}/Vertex_Decoder_Search/${log_name}/checkpoints" \
                #  --limit_train_batches ${lim_train_batches} \
                #  --limit_val_batches ${lim_val_batches} \
                #  --num_nodes 4 \

if [ $? -eq 0 ]; then
    echo "Job completed successfully"
else
    echo "Requeuing the job"
    scontrol requeue $SLURM_JOB_ID
fi