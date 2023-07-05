from typing import Any, Callable

from abc import ABC

from torch import Tensor, cat
import torch.nn as nn
from torch_geometric.nn.aggr import LSTMAggregation

import torchmetrics as tm

import matplotlib.pyplot as plt
import seaborn as sn

from .linear import ClassLinear
from ..util import FocalLoss, RecallLoss

class DecoderBase(nn.Module, ABC):
    '''Base class for all NuGraph decoders'''
    def __init__(self,
                 name: str,
                 planes: list[str],
                 classes: list[str],
                 loss_func: Callable,
                 task: str,
                 confusion: bool = False,
                 ignore_index: int = None):
        super().__init__()

        self.name = name
        self.planes = planes
        self.classes = classes

        self.loss_func = loss_func

        self.task = task

        self.acc_func = tm.Accuracy(task=task,
                                    num_classes=len(classes),
                                    average='none',
                                    ignore_index=ignore_index)

        self.confusion = nn.ModuleDict()
        if confusion:
            self.confusion[f'{self.name}_recall'] = tm.ConfusionMatrix(
                task=task,
                num_classes=len(classes),
                normalize='true',
                ignore_index=ignore_index)
            self.confusion[f'{self.name}_precision'] = tm.ConfusionMatrix(
                task=task,
                num_classes=len(classes),
                normalize='pred',
                ignore_index=ignore_index)

    def arrange(self, batch) -> tuple[Tensor, Tensor]:
        raise NotImplementedError

    def metrics(self, x: Tensor, y: Tensor, stage: str) -> dict[str, Any]:
        raise NotImplementedError

    def loss(self,
             batch,
             stage: str,
             confusion: bool = False):
        x, y = self.arrange(batch)
        metrics = self.metrics(x, y, stage)
        loss = self.loss_func(x, y)
        metrics[f'{self.name}_loss/{stage}'] = loss
        for cm in self.confusion.values():
            cm.update(x, y)
        return loss, metrics

    def draw_confusion_matrix(self, cm: tm.ConfusionMatrix) -> plt.Figure:
        '''Produce confusion matrix at end of epoch'''
        confusion = cm.compute().cpu()
        fig = plt.figure(figsize=[8,6])
        sn.heatmap(confusion,
                   xticklabels=self.classes,
                   yticklabels=self.classes,
                   vmin=0, vmax=1,
                   annot=True)
        plt.ylim(0, len(self.classes))
        plt.xlabel('Assigned label')
        plt.ylabel('True label')
        return fig

    def on_epoch_end(self,
                     logger: 'pl.loggers.TensorBoardLogger',
                     stage: str,
                     epoch: int) -> None:
        if not logger: return
        for name, cm in self.confusion.items():
            logger.experiment.add_figure(
                f'{name}/{stage}',
                self.draw_confusion_matrix(cm),
                global_step=epoch)
            cm.reset()

class SemanticDecoder(DecoderBase):
    """NuGraph semantic decoder module.

    Convolve down to a single node score per semantic class for each 2D graph,
    node, and remove intermediate node stores from data object.
    """
    def __init__(self,
                 node_features: int,
                 planes: list[str],
                 classes: list[str]):
        super().__init__('semantic',
                         planes,
                         classes,
                         RecallLoss(),
                         'multiclass',
                         confusion=True,
                         ignore_index=-1)

        self.net = nn.ModuleDict()
        for p in planes:
            self.net[p] = ClassLinear(node_features, 1, len(classes))

    def forward(self, x: dict[str, Tensor], batch: dict[str, Tensor]) -> dict[str, dict[str, Tensor]]:
        return { 'x_semantic': { p: self.net[p](x[p]).squeeze(dim=-1) for p in self.planes } }

    def arrange(self, batch) -> tuple[Tensor, Tensor]:
        x = cat([batch[p].x_semantic for p in self.planes], dim=0)
        y = cat([batch[p].y_semantic for p in self.planes], dim=0)
        return x, y

    def metrics(self, x: Tensor, y: Tensor, stage: str) -> dict[str, Any]:
        metrics = {}
        acc = 100. * self.acc_func(x, y)
        metrics[f'semantic_accuracy/{stage}'] = acc.mean()
        for c, a in zip(self.classes, acc):
            metrics[f'semantic_accuracy_class_{stage}/{c}'] = a
        return metrics

class FilterDecoder(DecoderBase):
    """NuGraph filter decoder module.

    Convolve down to a single node score, to identify and filter out
    graph nodes that are not part of the primary physics interaction
    """
    def __init__(self,
                 node_features: int,
                 planes: list[str],
                 classes: list[str]):
        super().__init__('filter',
                         planes,
                         ('noise', 'signal'),
                         nn.BCELoss(),
                         'binary',
                         confusion=True)

        num_features = len(classes) * node_features

        self.net = nn.ModuleDict()
        for p in planes:
            self.net[p] = nn.Sequential(
                nn.Linear(num_features, 1),
                nn.Sigmoid())

    def forward(self, x: dict[str, Tensor], batch: dict[str, Tensor]) -> dict[str, dict[str, Tensor]]:
        return { 'x_filter': { p: self.net[p](x[p].flatten(start_dim=1)).squeeze(dim=-1) for p in self.planes }}

    def arrange(self, batch) -> tuple[Tensor, Tensor]:
        x = cat([batch[p].x_filter for p in self.planes], dim=0)
        y = cat([(batch[p].y_semantic!=-1).float() for p in self.planes], dim=0)
        return x, y

    def metrics(self, x: Tensor, y: Tensor, stage: str) -> dict[str, Any]:
        metrics = {}
        acc = 100. * self.acc_func(x, y)
        metrics[f'filter_accuracy/{stage}'] = acc.mean()
        return metrics

class EventDecoder(DecoderBase):
    '''NuGraph event decoder module.

    Convolve graph node features down to a single classification score
    for the entire event
    '''
    def __init__(self,
                 node_features: int,
                 planes: list[str],
                 semantic_classes: list[str],
                 event_classes: list[str]):
        super().__init__('event',
                         planes,
                         event_classes,
                         RecallLoss(),
                         'multiclass',
                         confusion=True)

        self.pool = nn.ModuleDict()
        for p in planes:
            self.pool[p] = LSTMAggregation(
                in_channels=len(planes) * len(semantic_classes) * node_features,
                out_channels=node_features)
        self.net = nn.Sequential(
            nn.Linear(in_features=len(planes) * node_features,
                      out_features=len(event_classes)))

    def forward(self, x: dict[str, Tensor], batch: dict[str, Tensor]) -> dict[str, dict[str, Tensor]]:
        x = [ pool(x[p].flatten(1), batch[p]) for p, pool in self.pool.items() ]
        return { 'x': { 'evt': self.net(cat(x, dim=1)) }}

    def arrange(self, batch) -> tuple[Tensor, Tensor]:
        return batch['evt'].x, batch['evt'].y

    def metrics(self, x: Tensor, y: Tensor, stage: str) -> dict[str, Any]:
        metrics = {}
        acc = 100. * self.acc_func(x, y)
        metrics[f'event_accuracy/{stage}'] = acc.mean()
        for c, a in zip(self.classes, acc):
            metrics[f'event_accuracy_class_{stage}/{c}'] = a
        return metrics