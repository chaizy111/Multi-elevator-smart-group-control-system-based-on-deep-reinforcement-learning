"""Permutation-equivariant shared elevator encoder and conditional dual actor."""

from collections.abc import Sequence

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

ARCHITECTURE_VERSION = "shared-attention-128-v1"
RESIDUAL_VERSION = "insertion-prior-residual-v2"
FOCUSED_VERSION = "insertion-prior-focused-v3"


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
    prior_weights: torch.Tensor

    def __init__(
        self,
        *,
        attention: bool = True,
        candidates=False,
        prior_weights=(1.0, 0.2, 0.3, 1.0, 0.2, 0.0),
        residual_scale=2.0,
        policy_temperature=1.0,
        structured_residual=False,
        contextual_weights=True,
    ):
        super().__init__()
        self.use_candidates = candidates
        self.residual_scale = residual_scale
        self.policy_temperature = policy_temperature
        self.structured_residual = structured_residual
        self.contextual_weights = contextual_weights
        if policy_temperature <= 0 or (structured_residual and not candidates):
            raise ValueError("positive temperature and candidate features required")
        self.route_encoder = mlp(8, 32, 32)
        self.elevator_encoder = mlp(88, 128, 128)
        self.blocks = nn.ModuleList([AttentionBlock(), AttentionBlock()] if attention else [])
        self.floor_encoder = mlp(9, 32, 32)
        self.request_encoder = mlp(5, 32, 32)
        self.global_encoder = mlp(86, 64, 64)
        self.dispatch = (
            mlp(25, 6)
            if structured_residual and contextual_weights
            else nn.Sequential(nn.Linear(1, 6, bias=False))
            if structured_residual
            else mlp(230 if candidates else 224, 128, 1)
        )
        self.reposition = mlp(352, 128, 5)
        self.critic = mlp(352, 128, 1)
        if candidates:
            self.register_buffer("prior_weights", torch.tensor(prior_weights, dtype=torch.float32))
            for head in (self.dispatch, self.reposition):
                last = head[-1]
                assert isinstance(last, nn.Linear)
                nn.init.zeros_(last.weight)
                if last.bias is not None:
                    nn.init.zeros_(last.bias)

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
        if self.structured_residual:
            # Shared context changes six cost weights, preserving elevator equivariance.
            adjustment = self.residual_scale * torch.tanh(
                self.dispatch(
                    torch.cat((obs["global"].float(), obs["request"].float()), -1)
                    if self.contextual_weights
                    else torch.ones_like(obs["request"][:, :1]).float()
                )
            )
            dispatch = -(
                obs["candidates"].float() * (self.prior_weights + adjustment[:, None])
            ).sum(-1)
        else:
            dispatch_input = torch.cat((h, context[:, None, :].expand(-1, 8, -1)), -1)
            if self.use_candidates:
                dispatch_input = torch.cat((dispatch_input, obs["candidates"].float()), -1)
            dispatch = self.dispatch(dispatch_input).squeeze(-1)
        summary = pool(h, em)
        subject = (h * (obs["elevators"][:, :, 23] * em).unsqueeze(-1)).sum(1)
        reposition = self.reposition(torch.cat((subject, summary[:, :128], context), -1))
        if self.use_candidates:
            if not self.structured_residual:
                dispatch = self.residual_scale * torch.tanh(dispatch) - (
                    obs["candidates"].float() * self.prior_weights
                ).sum(-1)
            stay_prior = torch.tensor([2.0, 0.0, 0.0, 0.0, 0.0], device=reposition.device)
            reposition = self.residual_scale * torch.tanh(reposition) + stay_prior
        value = self.critic(torch.cat((summary, context), -1)).squeeze(-1)
        logits = torch.cat((dispatch, reposition), -1) / self.policy_temperature
        logits = logits.masked_fill(~obs["action_mask"].bool(), torch.finfo(logits.dtype).min)
        return logits, value

    def distribution(self, obs):
        if not torch.all(obs["action_mask"].any(-1)):
            raise ValueError("cannot sample a terminal/all-masked observation")
        logits, value = self(obs)
        return Categorical(logits=logits), value


def model_from_config(config: dict) -> ActorCritic:
    return ActorCritic(
        attention=config.get("attention", True),
        candidates=config.get("candidate_policy", False),
        prior_weights=config.get("prior_weights", (1.0, 0.2, 0.3, 1.0, 0.2, 0.0)),
        residual_scale=config.get("residual_scale", 2.0),
        policy_temperature=config.get("policy_temperature", 1.0),
        structured_residual=config.get("structured_residual", False),
        contextual_weights=config.get("contextual_weights", True),
    )
