"""NuGraph3 model architecture"""
import argparse
import warnings
import psutil

import torch
from torch.optim import AdamW
from torch.optim.lr_scheduler import OneCycleLR
from pytorch_lightning import LightningModule
from torch_geometric.data import Batch, HeteroData
from torch_geometric.utils import unbatch

from .encoder import Encoder
from .plane import PlaneNet
from .nexus import NexusNet
from .interaction import InteractionNet
from .decoders import SemanticDecoder, FilterDecoder, EventDecoder, VertexDecoder

from ...data import H5DataModule

T = torch.Tensor
TD = dict[str, T]

class NuGraph3(LightningModule):
    """PyTorch Lightning module for model training.

    Wrap the base model in a LightningModule wrapper to handle training and
    inference, and compute training metrics.

    Args:
        in_features: Number of input node features
        planar_features:
    """
    def __init__(self,
                 in_features: int = 4,
                 planar_features: int = 128,
                 nexus_features: int = 32,
                 interaction_features: int = 32,
                 planes: list[str] = ['u','v','y'],
                 semantic_classes: list[str] = ['MIP','HIP','shower','michel','diffuse'],
                 event_classes: list[str] = ['numu','nue','nc'],
                 num_iters: int = 5,
                 event_head: bool = False,
                 semantic_head: bool = True,
                 filter_head: bool = True,
                 vertex_head: bool = False,
                 checkpoint: bool = False,
                 lr: float = 0.001):
        super().__init__()

        warnings.filterwarnings("ignore", ".*NaN values found in confusion matrix.*")

        self.save_hyperparameters()

        self.planes = planes
        self.semantic_classes = semantic_classes
        self.event_classes = event_classes
        self.num_iters = num_iters
        self.lr = lr

        self.encoder = Encoder(in_features,
                               planar_features,
                               planes)

# Setu's addition
        
        self.plane_ascent = PlaneNet(in_features,
                                planar_features, 
                                planes, 
                                checkpoint=checkpoint)
        
        self.nexus_ascent = NexusNet(planar_features,
                                  nexus_features,
                                  planes,
                                  checkpoint=checkpoint)
        
        self.nexus_descent = NexusNet(interaction_features,
                                planar_features, 
                                planes, 
                                checkpoint=checkpoint)
        
        self.plane_descent = PlaneNet(planar_features,
                                  planar_features,
                                  planes,
                                  checkpoint=checkpoint)
        
        self.encoder_descent = Encoder(nexus_features, 
                                       planar_features, 
                                       planes)

        self.mix_net = torch.nn.ModuleDict()

        for p in planes:
            self.mix_net[p] = torch.nn.Sequential(
                torch.nn.Linear(in_features+planar_features,
                                planar_features),
                torch.nn.Tanh(),
                torch.nn.Linear(planar_features, planar_features),
                torch.nn.Tanh())

        self.decoders = []

        if event_head:
            self.event_decoder = EventDecoder(
                interaction_features,
                planes,
                event_classes)
            self.decoders.append(self.event_decoder)

        if semantic_head:
            self.semantic_decoder = SemanticDecoder(
                planar_features,
                planes,
                semantic_classes)
            self.decoders.append(self.semantic_decoder)

        if filter_head:
            self.filter_decoder = FilterDecoder(
                planar_features,
                planes,
            )
            self.decoders.append(self.filter_decoder)
            
        if vertex_head:
            self.vertex_decoder = VertexDecoder(
                interaction_features,
                planes,
                semantic_classes)
            self.decoders.append(self.vertex_decoder)

        if len(self.decoders) == 0:
            raise Exception('At least one decoder head must be enabled!')


    def forward(self, x: TD, edge_index_plane: TD, edge_index_nexus: TD,
                nexus: T, batch: TD) -> TD:
        m = self.encoder(x)
        for _ in range(self.num_iters):
            x_p = self.plane_ascent(m, edge_index_plane)
            x_n = self.nexus_ascent(x_p, edge_index_nexus, nexus)
            x_e = self.interaction_net(x_n, batch)
            x_n_d = self.nexus_descent(x_e, edge_index_plane, nexus)
            x_p_d = self.plane_descent(x_n_d, edge_index_plane)
            for p, net in self.mix_net.items():
                m[p] = torch.cat([x[p], x_n_d[p]], dim=-1)
                m[p] = net(m[p])
        ret = {}
        for decoder in self.decoders:
            ret.update(decoder(m, x_e, batch))
        return ret

# Setu's modifications end here
    def step(self, data: HeteroData | Batch,
             stage: str = None,
             confusion: bool = False):

        # if it's a single data instance, convert to batch manually
        if isinstance(data, Batch):
            batch = data
        else:
            batch = Batch.from_data_list([data])

        # unpack tensors to pass into forward function
        x = self(batch.collect('x'),
                 { p: batch[p, 'plane', p].edge_index for p in self.planes },
                 { p: batch[p, 'nexus', 'sp'].edge_index for p in self.planes },
                 torch.empty(batch['sp'].num_nodes, 0),
                 { p: batch[p].batch for p in self.planes })

        # append output tensors back onto input data object
        if isinstance(data, Batch):
            dlist = [ HeteroData() for i in range(data.num_graphs) ]
            for attr, planes in x.items():
                for p, t in planes.items():
                    if t.size(0) == data[p].num_nodes:
                        tlist = unbatch(t, data[p].batch)
                    elif t.size(0) == data.num_graphs:
                        tlist = unbatch(t, torch.arange(data.num_graphs))
                    else:
                        raise Exception(f'don\'t know how to unbatch attribute {attr}')
                    for it_d, it_t in zip(dlist, tlist):
                        it_d[p][attr] = it_t
            tmp = Batch.from_data_list(dlist)
            data.update(tmp)
            for attr, planes in x.items():
                for p in planes:
                    data._slice_dict[p][attr] = tmp._slice_dict[p][attr]
                    data._inc_dict[p][attr] = tmp._inc_dict[p][attr]

        else:
            for key, value in x.items():
                data.set_value_dict(key, value)

        total_loss = 0.
        total_metrics = {}
        for decoder in self.decoders:
            loss, metrics = decoder.loss(data, stage, confusion)
            total_loss += loss
            total_metrics.update(metrics)
            decoder.finalize(data)

        return total_loss, total_metrics

    def on_train_start(self):
        hpmetrics = { 'max_lr': self.hparams.lr }
        self.logger.log_hyperparams(self.hparams, metrics=hpmetrics)
        self.max_mem_cpu = 0.
        self.max_mem_gpu = 0.

        scalars = {
            'loss': {'loss': [ 'Multiline', [ 'loss/train', 'loss/val' ]]},
            'acc': {}
        }
        for c in self.semantic_classes:
            scalars['acc'][c] = [ 'Multiline', [
                f'semantic_accuracy_class_train/{c}',
                f'semantic_accuracy_class_val/{c}'
            ]]
        self.logger.experiment.add_custom_scalars(scalars)

    def training_step(self,
                      batch,
                      batch_idx: int) -> float:
        loss, metrics = self.step(batch, 'train')
        self.log('loss/train', loss, batch_size=batch.num_graphs, prog_bar=True)
        self.log_dict(metrics, batch_size=batch.num_graphs)
        self.log_memory(batch, 'train')
        return loss

    def validation_step(self,
                        batch,
                        batch_idx: int) -> None:
        loss, metrics = self.step(batch, 'val', True)
        self.log('loss/val', loss, batch_size=batch.num_graphs)
        self.log_dict(metrics, batch_size=batch.num_graphs)

    def on_validation_epoch_end(self) -> None:
        epoch = self.trainer.current_epoch + 1
        for decoder in self.decoders:
            decoder.on_epoch_end(self.logger, 'val', epoch)

    def test_step(self,
                  batch,
                  batch_idx: int = 0) -> None:
        loss, metrics = self.step(batch, 'test', True)
        self.log('loss/test', loss, batch_size=batch.num_graphs)
        self.log_dict(metrics, batch_size=batch.num_graphs)
        self.log_memory(batch, 'test')

    def on_test_epoch_end(self) -> None:
        epoch = self.trainer.current_epoch + 1
        for decoder in self.decoders:
            decoder.on_epoch_end(self.logger, 'test', epoch)

    def predict_step(self,
                     batch: Batch,
                     batch_idx: int = 0) -> Batch:
        self.step(batch)
        return batch

    def configure_optimizers(self) -> tuple:
        optimizer = AdamW(self.parameters(),
                          lr=self.lr)
        onecycle = OneCycleLR(
                optimizer,
                max_lr=self.lr,
                total_steps=self.trainer.estimated_stepping_batches)
        return [optimizer], {'scheduler': onecycle, 'interval': 'step'}

    def log_memory(self, batch: Batch, stage: str) -> None:
        # log CPU memory
        if not hasattr(self, 'max_mem_cpu'):
            self.max_mem_cpu = 0.
        cpu_mem = psutil.Process().memory_info().rss / float(1073741824)
        self.max_mem_cpu = max(self.max_mem_cpu, cpu_mem)
        self.log(f'memory_cpu/{stage}', self.max_mem_cpu,
                 batch_size=batch.num_graphs, reduce_fx=torch.max)

        # log GPU memory
        if not hasattr(self, 'max_mem_gpu'):
            self.max_mem_gpu = 0.
        if self.device != torch.device('cpu'):
            gpu_mem = torch.cuda.memory_reserved(self.device)
            gpu_mem = float(gpu_mem) / float(1073741824)
            self.max_mem_gpu = max(self.max_mem_gpu, gpu_mem)
            self.log(f'memory_gpu/{stage}', self.max_mem_gpu,
                     batch_size=batch.num_graphs, reduce_fx=torch.max)

    @staticmethod
    def add_model_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        '''Add argparse argpuments for model structure'''
        model = parser.add_argument_group('model', 'NuGraph3 model configuration')
        model.add_argument('--num-iters', type=int, default=5,
                           help='Number of message-passing iterations')
        model.add_argument('--in-feats', type=int, default=4,
                           help='Number of input node features')
        model.add_argument('--planar-feats', type=int, default=128,
                           help='Hidden dimensionality of planar convolutions')
        model.add_argument('--nexus-feats', type=int, default=32,
                           help='Hidden dimensionality of nexus convolutions')
        model.add_argument('--interaction-feats', type=int, default=32,
                           help='Hidden dimensionality of interaction layer')
        model.add_argument('--event', action='store_true', default=False,
                           help='Enable event classification head')
        model.add_argument('--semantic', action='store_true', default=False,
                           help='Enable semantic segmentation head')
        model.add_argument('--filter', action='store_true', default=False,
                           help='Enable background filter head')
        model.add_argument('--vertex', action='store_true', default=False,
                           help='Enable vertex regression head')
        model.add_argument('--no-checkpointing', action='store_true', default=False,
                           help='Disable checkpointing during training')
        model.add_argument('--epochs', type=int, default=80,
                           help='Maximum number of epochs to train for')
        model.add_argument('--learning-rate', type=float, default=0.001,
                           help='Max learning rate during training')
        return parser

    @classmethod
    def from_args(cls, args: argparse.Namespace, nudata: H5DataModule) -> 'NuGraph3':
        return cls(
            in_features=args.in_feats,
            planar_features=args.planar_feats,
            nexus_features=args.nexus_feats,
            interaction_features=args.interaction_feats,
            planes=nudata.planes,
            semantic_classes=nudata.semantic_classes,
            event_classes=nudata.event_classes,
            num_iters=args.num_iters,
            event_head=args.event,
            semantic_head=args.semantic,
            filter_head=args.filter,
            vertex_head=args.vertex,
            checkpoint=not args.no_checkpointing,
            lr=args.learning_rate)
