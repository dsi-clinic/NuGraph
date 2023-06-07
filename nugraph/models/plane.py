from torch import Tensor, cat
import torch.nn as nn
from torch.utils.checkpoint import checkpoint

from torch_geometric.nn import MessagePassing

from .linear import ClassLinear

class MessagePassing2D(MessagePassing):

    propagate_type = { 'x': Tensor }

    def __init__(self,
                 in_features: int,
                 node_features: int,
                 edge_features: int,
                 num_classes: int,
                 aggr: str = 'add'):
        super().__init__(node_dim=0, aggr=aggr)

        self.edge_net = nn.Sequential(
            ClassLinear(2 * (in_features + node_features),
                        edge_features,
                        num_classes),
            nn.Tanh(),
            ClassLinear(edge_features,
                        1,
                        num_classes),
            nn.Softmax(dim=1))

        self.node_net = nn.Sequential(
            ClassLinear(2 * (in_features + node_features),
                        node_features,
                        num_classes),
            nn.Tanh(),
            ClassLinear(node_features,
                        node_features,
                        num_classes),
            nn.Tanh())

    def forward(self, x: Tensor, edge_index: Tensor):
        return self.propagate(edge_index, x=x, size=None)

    def message(self, x_i: Tensor, x_j: Tensor):
        return self.edge_net(cat((x_i, x_j), dim=-1).detach()) * x_j

    def update(self, aggr_out: Tensor, x: Tensor):
        return self.node_net(cat((x, aggr_out), dim=-1))

class PlaneNet(nn.Module):
    '''Module to convolve within each detector plane'''
    def __init__(self,
                 in_features: int,
                 node_features: int,
                 edge_features: int,
                 num_classes: int,
                 planes: list[str],
                 aggr: str = 'add'):
        super().__init__()

        self.net = nn.ModuleDict()
        for p in planes:
            self.net[p] = MessagePassing2D(in_features,
                                           node_features,
                                           edge_features,
                                           num_classes,
                                           aggr)

    def forward(self, x: dict[str, Tensor], edge_index: dict[str, Tensor]) -> None:
        for p in self.net:
            x[p] = checkpoint(self.net[p], x[p], edge_index[p])