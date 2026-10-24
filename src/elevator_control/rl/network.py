"""Permutation-equivariant shared elevator encoder and conditional dual actor."""

from collections.abc import Sequence

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

ARCHITECTURE_VERSION = "shared-attention-128-v1"
CANDIDATE_ARCHITECTURE_VERSION = "shared-attention-insertion-input-v1"


def mlp(*sizes: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i, (a, b) in enumerate(zip(sizes[:-1], sizes[1:], strict=True)):
        layers.append(nn.Linear(a, b))
        if i < len(sizes) - 2:
            layers.append(nn.SiLU())
    return nn.Sequential(*layers)


def tensor_observations(
    observations: dict | Sequence[dict], device="cpu"
) -> dict[str, torch.Tensor]:
    rows = [observations] if isinstance(observations, dict) else observations
    return {k: torch.as_tensor(np.stack([o[k] for o in rows]), device=device) for k in rows[0]}


def pool(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    valid = mask.unsqueeze(-1)
    mean = (x * valid).sum(-2) / valid.sum(-2).clamp(min=1)
    maximum = x.masked_fill(~valid, torch.finfo(x.dtype).min).max(-2).values
    return torch.cat((mean, maximum), -1)


class AttentionBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.attention = nn.MultiheadAttention(128, 4, dropout=0, batch_first=True)
        self.norm1 = nn.LayerNorm(128)
        self.ffn = mlp(128, 256, 128)
        self.norm2 = nn.LayerNorm(128)

    def forward(self, x, mask):
        attended, _ = self.attention(x, x, x, key_padding_mask=~mask, need_weights=False)
        x = self.norm1(x + attended)
        x = self.norm2(x + self.ffn(x))
        return x * mask.unsqueeze(-1)


class ActorCritic(nn.Module):
    def __init__(self, *, attention: bool = True, candidate_inputs: bool = False):
        super().__init__()
        self.use_attention = attention
        self.candidate_inputs = candidate_inputs
        self.route_encoder = mlp(8, 32, 32)
        self.elevator_encoder = mlp(88, 128, 128)
        self.blocks = nn.ModuleList([AttentionBlock(), AttentionBlock()] if attention else [])
        self.floor_encoder = mlp(9, 32, 32)
        self.request_encoder = mlp(5, 32, 32)
        self.global_encoder = mlp(86, 64, 64)
        self.dispatch = mlp(230 if candidate_inputs else 224, 128, 1)
        self.reposition = mlp(352, 128, 5)
        self.critic = mlp(352, 128, 1)

    def forward(self, obs: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
        em, fm = obs["elevator_mask"].bool(), obs["floor_mask"].bool()
        routes = self.route_encoder(obs["elevator_routes"].float())
        route_summary = pool(routes, fm[:, None, :].expand(-1, 8, -1))
        h = self.elevator_encoder(
            torch.cat((obs["elevators"].float(), route_summary), -1)
        ) * em.unsqueeze(-1)
        for block in self.blocks:
            h = block(h, em)
        floors = pool(self.floor_encoder(obs["floors"].float()), fm)
        request = self.request_encoder(obs["request"].float())
        global_context = self.global_encoder(
            torch.cat((obs["global"].float(), floors, obs["decision_kind"].float()), -1)
        )
        context = torch.cat((request, global_context), -1)
        dispatch_input = torch.cat((h, context[:, None, :].expand(-1, 8, -1)), -1)
        if self.candidate_inputs:
            dispatch_input = torch.cat((dispatch_input, obs["candidates"].float()), -1)
        dispatch = self.dispatch(dispatch_input).squeeze(-1)
        summary = pool(h, em)
        subject = (h * (obs["elevators"][:, :, 23] * em).unsqueeze(-1)).sum(1)
        reposition = self.reposition(torch.cat((subject, summary[:, :128], context), -1))
        value = self.critic(torch.cat((summary, context), -1)).squeeze(-1)
        logits = torch.cat((dispatch, reposition), -1)
        logits = logits.masked_fill(~obs["action_mask"].bool(), torch.finfo(logits.dtype).min)
        return logits, value

    def distribution(self, obs):
        if not torch.all(obs["action_mask"].any(-1)):
            raise ValueError("cannot sample a terminal/all-masked observation")
        logits, value = self(obs)
        return Categorical(logits=logits), value
