"""Small synchronous vector PPO with true event-time discounting and resumable logs."""

import csv
import importlib.metadata
import json
import math
import platform
import random
import signal
import threading
import time
import traceback
from pathlib import Path
from typing import cast

import numpy as np
import torch
from pydantic import Field, field_validator

from elevator_control.config.schema import Pattern, Schema, SimulationConfig, canonical_hash
from elevator_control.env.environment import ElevatorEnv
from elevator_control.evaluation.metrics import calculate, reward_from_costs
from elevator_control.rl.buffer import generalized_advantages
from elevator_control.rl.checkpoint import initialize_network, save_checkpoint, versions_for
from elevator_control.rl.network import ActorCritic, tensor_observations
from elevator_control.rl.validation import expanded_validation, validation_score
from elevator_control.storage.artifacts import atomic_json

HELD_OUT = {(12, 3), (18, 5)}


class TrainingConfig(Schema):
    seed: int = 42
    total_decisions: int = Field(default=10000, ge=1)
    num_envs: int = Field(default=1, ge=1, le=16)
    rollout_steps: int = Field(default=256, ge=1)
    minibatch: int = Field(default=128, ge=1)
    epochs: int = Field(default=4, ge=1)
    learning_rate: float = Field(default=3e-4, gt=0)
    min_learning_rate: float = Field(default=3e-5, gt=0)
    gamma: float = Field(default=0.99, gt=0, le=1)
    gae_lambda: float = Field(default=0.95, gt=0, le=1)
    dt_ref: float = Field(default=10, gt=0)
    clip: float = Field(default=0.2, gt=0)
    value_coefficient: float = Field(default=0.5, ge=0)
    entropy_coefficient: float = Field(default=0.01, ge=0)
    target_kl: float = Field(default=0.02, gt=0)
    max_grad_norm: float = Field(default=0.5, gt=0)
    validation_interval: int = Field(default=20, ge=1)
    device: str = "cpu"
    attention: bool = True
    dispatch_only: bool = False
    domain_randomization: bool = False
    stage: str = "T0"
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    scenarios: list[SimulationConfig] = Field(default_factory=list)
    candidate_inputs: bool = False
    validation_scenarios: list[SimulationConfig] = Field(default_factory=list)
    validation_limits: dict[str, float] = Field(default_factory=dict)
    validate_initial: bool = False

    @field_validator("validation_limits")
    @classmethod
    def validate_limits(cls, limits):
        allowed = {"mean_wait_s", "p95_wait_s", "distance_floors"}
        if any(k not in allowed or not math.isfinite(v) or v <= 0 for k, v in limits.items()):
            raise ValueError("validation limits must be supported, positive and finite")
        return limits


def configure_torch(seed: int):
    torch.set_num_threads(1)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def append_row(path: Path, row: dict):
    exists = path.exists()
    with path.open("a", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def sample_config(config: TrainingConfig, rng: np.random.Generator) -> SimulationConfig:
    choices = config.scenarios or [config.simulation]
    cfg = choices[int(rng.integers(len(choices)))].model_copy(deep=True)
    if config.domain_randomization:
        while True:
            f, e = int(rng.integers(5, 21)), int(rng.integers(2, 7))
            if (f, e) not in HELD_OUT:
                break
        cfg.building.initial_floors = None
        cfg.building.floor_count = f
        cfg.building.elevator_count = e
        cfg.building.capacity = int(rng.choice([6, 12, 20]))
        cfg.physics.seconds_per_floor = float(rng.uniform(1.5, 3))
        cfg.traffic.pattern = cast(
            Pattern, str(rng.choice(["normal", "morning", "evening", "interfloor", "burst"]))
        )
        cfg.traffic.arrival_rate_per_min = e * int(rng.choice([1, 3, 5]))
    if (cfg.building.floor_count, cfg.building.elevator_count) in HELD_OUT:
        raise ValueError("held-out building excluded from training and validation")
    cfg.seed = int(rng.integers(0, 1000000))
    return cfg


def enforce_dispatch_only(obs: dict, enabled: bool):
    if enabled and obs["decision_kind"][1]:
        obs["action_mask"][9:] = False


def validate_policy(model: ActorCritic, config: TrainingConfig, device: str) -> dict:
    if config.validation_scenarios:
        return expanded_validation(model, config, device)
    # Immutable seed range disjoint from training; never used for optimizer updates.
    configs = []
    for i, base in enumerate((config.scenarios or [config.simulation])[:3]):
        cfg = base.model_copy(deep=True)
        cfg.seed = 2000000 + i
        configs.append(cfg)
    results = []
    for cfg in configs:
        env = ElevatorEnv(cfg, candidate_inputs=config.candidate_inputs)
        obs, _ = env.reset(seed=cfg.seed)
        enforce_dispatch_only(obs, config.dispatch_only)
        while env.sim and not env.sim.done:
            with torch.no_grad():
                dist, _ = model.distribution(tensor_observations(obs, device))
                action = int(dist.logits.argmax(-1).item())
            obs, _, term, trunc, _ = env.step(action)
            enforce_dispatch_only(obs, config.dispatch_only)
            if term or trunc:
                break
        assert env.sim is not None
        metrics = calculate(env.sim)["final"]
        results.append(
            dict(
                seed=cfg.seed,
                cost=-reward_from_costs(env.sim.costs, cfg),
                completion_ratio=metrics["completion_ratio"],
                mean_wait_s=metrics["mean_wait_s"],
                p95_wait_s=metrics["p95_wait_s"],
            )
        )
    return dict(
        complete=all(r["completion_ratio"] == 1 for r in results),
        cost=float(np.mean([r["cost"] for r in results])),
        mean_wait=float(
            np.mean([r["mean_wait_s"] for r in results if r["mean_wait_s"] is not None])
        )
        if any(r["mean_wait_s"] is not None for r in results)
        else None,
        p95=float(np.mean([r["p95_wait_s"] for r in results if r["p95_wait_s"] is not None]))
        if any(r["p95_wait_s"] is not None for r in results)
        else None,
        results=results,
    )


def train(
    config: TrainingConfig,
    output: str | Path,
    *,
    resume: str | None = None,
    initialize: str | None = None,
    migrate_candidate_inputs: bool = False,
) -> Path:
    configure_torch(config.seed)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    device = config.device
    model = ActorCritic(attention=config.attention, candidate_inputs=config.candidate_inputs).to(
        device
    )
    versions = versions_for(config.candidate_inputs)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate, eps=1e-5)
    rng = np.random.default_rng(config.seed)
    steps, update, episodes, truncated_episodes = 0, 0, 0, 0
    best = (float("inf"), float("inf"))
    latest_validation = {}
    saved_seeds: list[int] = []
    if resume or initialize:
        data = torch.load(str(resume or initialize), map_location=device, weights_only=False)
        initialize_network(
            model, data, migrate_candidate_inputs=migrate_candidate_inputs and not resume
        )
        if resume:
            saved = TrainingConfig.model_validate(data["config"])
            if canonical_hash(saved) != canonical_hash(config):
                raise ValueError(
                    "resume config mismatch; initialize a new curriculum stage explicitly"
                )
            optimizer.load_state_dict(data["optimizer"])
            steps, update, episodes = data["steps"], data["update"], data["episodes"]
            rng.bit_generator.state = data["rng"]
            torch.set_rng_state(data["torch_rng"].cpu())
            random.setstate(data["python_rng"])
            np.random.set_state(data["numpy_rng"])
            best = tuple(data["best"])
            truncated_episodes = data.get("truncated_episodes", 0)
            saved_seeds = data.get("training_trace_seeds", [])
            latest_validation = data.get("validation", {})
            if steps >= config.total_decisions:
                print(f"already complete steps={steps} output={output}", flush=True)
                return output
    atomic_json(output / "config.json", config.model_dump(mode="json"))
    atomic_json(
        output / "split_manifest.json",
        dict(
            training_seed_range=[0, 999999],
            validation_seeds=[2000000 + i for i in range(min(3, len(config.scenarios) or 1))],
            test_seed_range=[9001, 99999],
            test_seed_note="test evaluation 9001..99999 is reserved; training seed collisions checked below",
            held_out_buildings=sorted(HELD_OUT),
            versions=versions,
            training_trace_seeds=[],
        ),
    )
    # Train seeds use 100000..999999, strictly disjoint from evaluation 9001..99999.
    envs = []
    observations = []
    used_seeds = saved_seeds.copy()

    def reset_env(i: int):
        cfg = sample_config(config, rng)
        cfg.seed = int(rng.integers(100000, 1000000))
        used_seeds.append(cfg.seed)
        env = ElevatorEnv(cfg, candidate_inputs=config.candidate_inputs)
        obs, _ = env.reset(seed=cfg.seed)
        enforce_dispatch_only(obs, config.dispatch_only)
        assert env.sim is not None
        append_row(
            output / "episodes.csv",
            dict(
                environment_id=i,
                episode_id=len(used_seeds),
                seed=cfg.seed,
                config_hash=canonical_hash(cfg),
                trace_hash=env.sim.trace.sha256,
                config_json=json.dumps(cfg.model_dump(mode="json"), sort_keys=True),
            ),
        )
        if i < len(envs):
            envs[i] = env
            observations[i] = obs
        else:
            envs.append(env)
            observations.append(obs)

    for i in range(config.num_envs):
        reset_env(i)
    start = time.perf_counter()
    print(
        f"device={device} seed={config.seed} budget={config.total_decisions} output={output} validation=2000000+ stage={config.stage}",
        flush=True,
    )
    initial = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    def checkpoint():
        payload = dict(
            network=model.state_dict(),
            optimizer=optimizer.state_dict(),
            scheduler=dict(kind="linear", steps=steps, budget=config.total_decisions),
            steps=steps,
            update=update,
            episodes=episodes,
            truncated_episodes=truncated_episodes,
            training_trace_seeds=used_seeds.copy(),
            config=config.model_dump(mode="json"),
            versions=versions,
            rng=rng.bit_generator.state,
            torch_rng=torch.get_rng_state(),
            python_rng=random.getstate(),
            numpy_rng=np.random.get_state(),
            best=best,
            validation=latest_validation,
            dependencies={
                n: importlib.metadata.version(n)
                for n in ["torch", "numpy", "gymnasium", "pydantic"]
            },
            platform=platform.platform(),
            selection="complete; constraints then mean wait then P95"
            if config.validation_scenarios
            else "complete-service validation cost; P95 tie break",
            resume_semantics="statistical; update boundary checkpoint, reset simulator episodes",
        )
        save_checkpoint(output / "checkpoints/last.pt", payload)
        return payload

    if config.validate_initial and not resume:
        model.eval()
        latest_validation = validate_policy(model, config, device)
        if config.validation_scenarios:
            atomic_json(output / "validation-results" / "0.json", latest_validation)
            best = validation_score(latest_validation)
        else:
            best = (latest_validation["cost"], latest_validation["p95"] or 0)
        payload = checkpoint()
        if latest_validation["complete"]:
            save_checkpoint(output / "checkpoints/best.pt", payload)
        model.train()
    stop_requested = False
    previous_handler = None
    if threading.current_thread() is threading.main_thread():
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_stop(signum, frame):
            nonlocal stop_requested
            stop_requested = True

        signal.signal(signal.SIGINT, request_stop)
    try:
        while steps < config.total_decisions:
            update += 1
            rollout = []
            batch_start = time.perf_counter()
            for _ in range(
                min(
                    config.rollout_steps,
                    (config.total_decisions - steps + config.num_envs - 1) // config.num_envs,
                )
            ):
                obs_batch = tensor_observations(observations, device)
                with torch.no_grad():
                    distribution, values = model.distribution(obs_batch)
                    actions = distribution.sample()
                    old_log = distribution.log_prob(actions)
                row = []
                next_obs = []
                for i, env in enumerate(envs):
                    obs, r, term, trunc, info = env.step(int(actions[i].item()))
                    enforce_dispatch_only(obs, config.dispatch_only)
                    next_obs.append(obs)
                    row.append(
                        dict(
                            obs=observations[i],
                            action=int(actions[i].item()),
                            log_prob=float(old_log[i].item()),
                            value=float(values[i].item()),
                            reward=r,
                            delta_t=info["delta_t_s"],
                            terminated=term,
                            boundary=term or trunc,
                            costs=info["reward_components"],
                            kind=info["decision_kind"],
                            next_value=0.0,
                            episode_id=episodes,
                            environment_id=i,
                        )
                    )
                with torch.no_grad():
                    _, next_values = model(tensor_observations(next_obs, device))
                for i, transition in enumerate(row):
                    transition["next_value"] = (
                        float(next_values[i].item()) if not transition["terminated"] else 0.0
                    )
                    observations[i] = next_obs[i]
                    if transition["boundary"]:
                        episodes += 1
                        truncated_episodes += not transition["terminated"]
                        reset_env(i)
                rollout.append(row)
                steps += config.num_envs
            sampling_s = time.perf_counter() - batch_start

            def array(key, transitions=rollout):
                return np.asarray([[x[key] for x in row] for row in transitions])

            boundaries = array("boundary")
            boundaries[-1, :] = True
            advantages, returns = generalized_advantages(
                array("reward"),
                array("value"),
                array("next_value"),
                array("delta_t"),
                array("terminated"),
                boundaries,
                gamma=config.gamma,
                lam=config.gae_lambda,
                dt_ref=config.dt_ref,
            )
            flat = [x for row in rollout for x in row]
            obs_t = tensor_observations([x["obs"] for x in flat], device)
            actions_t = torch.tensor([x["action"] for x in flat], device=device)
            old_log_t = torch.tensor([x["log_prob"] for x in flat], device=device)
            advantages_t = torch.as_tensor(advantages.reshape(-1), device=device)
            advantages_t = (advantages_t - advantages_t.mean()) / advantages_t.std(
                unbiased=False
            ).clamp(min=1e-8)
            returns_t = torch.as_tensor(returns.reshape(-1), device=device)
            lr = config.learning_rate + (config.min_learning_rate - config.learning_rate) * min(
                1, steps / config.total_decisions
            )
            for group in optimizer.param_groups:
                group["lr"] = lr
            losses = []
            head_grad = {"dispatch": 0.0, "reposition": 0.0}
            train_start = time.perf_counter()
            for _epoch in range(config.epochs):
                permutation = rng.permutation(len(flat))
                stop = False
                for offset in range(0, len(flat), config.minibatch):
                    indices = torch.as_tensor(
                        permutation[offset : offset + config.minibatch], device=device
                    )
                    batch = {k: v[indices] for k, v in obs_t.items()}
                    dist, value = model.distribution(batch)
                    log_prob = dist.log_prob(actions_t[indices])
                    log_ratio = log_prob - old_log_t[indices]
                    ratio = log_ratio.exp()
                    a = advantages_t[indices]
                    policy_loss = -torch.minimum(
                        ratio * a, ratio.clamp(1 - config.clip, 1 + config.clip) * a
                    ).mean()
                    value_loss = (value - returns_t[indices]).square().mean()
                    entropy = dist.entropy()
                    loss = (
                        policy_loss
                        + config.value_coefficient * value_loss
                        - config.entropy_coefficient * entropy.mean()
                    )
                    if not torch.isfinite(loss):
                        raise FloatingPointError("nonfinite PPO loss")
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    for name, head in [
                        ("dispatch", model.dispatch),
                        ("reposition", model.reposition),
                    ]:
                        head_grad[name] += sum(
                            float(p.grad.detach().norm().item())
                            for p in head.parameters()
                            if p.grad is not None
                        )
                    grad_norm = torch.nn.utils.clip_grad_norm_(
                        model.parameters(), config.max_grad_norm
                    )
                    if not torch.isfinite(grad_norm):
                        raise FloatingPointError("nonfinite PPO gradient")
                    optimizer.step()
                    with torch.no_grad():
                        kl = ((ratio - 1) - log_ratio).mean().item()
                        heads = batch["decision_kind"][:, 0].bool()
                        h_dispatch = float(entropy[heads].mean().item()) if heads.any() else 0.0
                        h_reposition = (
                            float(entropy[~heads].mean().item()) if (~heads).any() else 0.0
                        )
                        losses.append(
                            (
                                policy_loss.item(),
                                value_loss.item(),
                                kl,
                                float(((ratio - 1).abs() > config.clip).float().mean().item()),
                                float(grad_norm.item()),
                                h_dispatch,
                                h_reposition,
                            )
                        )
                    if kl > 1.5 * config.target_kl:
                        stop = True
                        break
                if stop:
                    break
            average = np.mean(losses, axis=0)
            raw_costs = {
                k: sum(x["costs"][k] for x in flat) for k in ["wait", "ride", "energy", "fairness"]
            }
            value_array = array("value").reshape(-1)
            variance = np.var(returns.reshape(-1))
            row = dict(
                step=steps,
                update=update,
                episodes=episodes,
                simulation_seconds=float(array("delta_t").sum()),
                reward_mean=float(array("reward").mean()),
                **raw_costs,
                policy_loss=float(average[0]),
                value_loss=float(average[1]),
                kl=float(average[2]),
                clip_fraction=float(average[3]),
                gradient_norm=float(average[4]),
                dispatch_entropy=float(average[5]),
                reposition_entropy=float(average[6]),
                dispatch_samples=sum(x["kind"] == "dispatch" for x in flat),
                reposition_samples=sum(x["kind"] == "reposition" for x in flat),
                dispatch_gradient=head_grad["dispatch"],
                reposition_gradient=head_grad["reposition"],
                explained_variance=float(1 - np.var(returns.reshape(-1) - value_array) / variance)
                if variance > 0
                else 0,
                learning_rate=lr,
                sampling_per_second=len(flat) / max(sampling_s, 1e-9),
                training_per_second=len(flat) / max(time.perf_counter() - train_start, 1e-9),
                truncation_rate=truncated_episodes / max(1, episodes),
                elapsed_s=time.perf_counter() - start,
            )
            append_row(output / "updates.csv", row)
            if update % config.validation_interval == 0 or steps >= config.total_decisions:
                model.eval()
                latest_validation = validate_policy(model, config, device)
                append_row(
                    output / "validation.csv",
                    dict(
                        step=steps,
                        cost=latest_validation["cost"],
                        p95=latest_validation["p95"],
                        mean_wait=latest_validation["mean_wait"],
                        complete=latest_validation["complete"],
                    ),
                )
                if config.validation_scenarios:
                    atomic_json(output / "validation-results" / f"{steps}.json", latest_validation)
                score = (
                    validation_score(latest_validation)
                    if config.validation_scenarios
                    else (latest_validation["cost"], latest_validation["p95"] or 0)
                )
                improved = latest_validation["complete"] and score < best
                if improved:
                    best = score
                payload = checkpoint()
                if improved:
                    save_checkpoint(output / "checkpoints/best.pt", payload)
                model.train()
            changed = sum(
                not torch.equal(initial[k], v.detach().cpu()) for k, v in model.state_dict().items()
            )
            atomic_json(
                output / "progress.json",
                dict(
                    status="RUNNING",
                    steps=steps,
                    budget=config.total_decisions,
                    updates=update,
                    episodes=episodes,
                    device=device,
                    elapsed_s=time.perf_counter() - start,
                    changed_tensors=changed,
                    validation=latest_validation,
                ),
            )
            print(
                f"step={steps} update={update} episodes={episodes} loss={average[0]:.4f}/{average[1]:.4f} dispatch/reposition={row['dispatch_samples']}/{row['reposition_samples']} rate={row['sampling_per_second']:.0f}/s",
                flush=True,
            )
            if stop_requested:
                raise KeyboardInterrupt
        checkpoint()
        atomic_json(
            output / "progress.json",
            dict(
                status="COMPLETED",
                steps=steps,
                budget=config.total_decisions,
                updates=update,
                episodes=episodes,
                device=device,
                elapsed_s=time.perf_counter() - start,
                changed_tensors=changed,
                validation=latest_validation,
            ),
        )
    except KeyboardInterrupt:
        checkpoint()
        atomic_json(
            output / "progress.json",
            dict(status="INTERRUPTED", steps=steps, updates=update, device=device),
        )
        raise
    except Exception as error:
        atomic_json(
            output / "failure.json",
            dict(
                code=type(error).__name__,
                message=str(error),
                traceback=traceback.format_exc(),
                steps=steps,
                update=update,
            ),
        )
        atomic_json(
            output / "progress.json",
            dict(status="FAILED", steps=steps, updates=update, device=device, message=str(error)),
        )
        raise
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)
        atomic_json(
            output / "split_manifest.json",
            dict(
                training_seed_range=[100000, 999999],
                training_trace_seeds=used_seeds,
                validation_seeds=[2000000 + i for i in range(min(3, len(config.scenarios) or 1))],
                test_seed_range=[9001, 99999],
                held_out_buildings=sorted(HELD_OUT),
                versions=versions,
            ),
        )
    (output / "training.log").write_text(
        f"device={device} seed={config.seed} steps={steps} updates={update} platform={platform.platform()}\n"
    )
    print(f"completed steps={steps} checkpoint={output / 'checkpoints/last.pt'}", flush=True)
    return output
