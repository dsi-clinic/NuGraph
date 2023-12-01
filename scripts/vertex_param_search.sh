#!/bin/bash
#SBATCH --job-name=fermi2
#SBATCH --output=/net/projects/fermi-2/logs/%A_%a.out
#SBATCH --error=/net/projects/fermi-2/logs/%A_%a.err
#SBATCH --time=12:00:00
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --gres=gpu:1
#SBATCH --constraint=a100
#SBATCH --mem-per-cpu=64G


# srun -p general -t "12:00:00" --mem "64G" --cpus-per-task 12 --gres gpu:1 --constraint a100 --pty /bin/bash


# pull in passed arguments
args=("$@")

# make logdir under username
username=$USER
logdir="../../../../net/projects/fermi-2/logs/$username"
mkdir -p "$logdir"
echo $logdir

# aggregator
vtx_aggr=${args[0]}

# mlp features
vtx_mlp_features=${args[1]}

# lstm features
if [ ${#args[@]} == 3 ]; then
    vtx_lstm_features=${args[2]}
    log_name="log_aggr_${vtx_aggr}_mlpfeats_${vtx_mlp_features}_lstmfeats_${vtx_lstm_features}"

else
    log_name="log_aggr_${vtx_aggr}_mlpfeats_${vtx_mlp_features}"
fi


# set variables
lim_train_batches=1
lim_val_batches=1
epochs=80 #CHANGE


# set directory
cd "$(dirname "$0")"


# run training
python train.py \
                 --data-path /net/projects/fermi-2/CHEP2023.gnn.h5 \
                 --logdir ${logdir} \
                 --name  "Vertex_Decoder_Search"\
                 --version ${log_name} \
                 --semantic \
                 --filter \
                 --vertex \
                 --vertex-aggr ${vtx_aggr} \
                 --vertex-lstm-feats ${vtx_lstm_features} \
                 --vertex-mlp-feats ${vtx_mlp_features} \
                 --epochs ${epochs}
                #  --limit_train_batches ${lim_train_batches}\
                #  --limit_val_batches ${lim_val_batches}\
                 #  --num_nodes 4 \

