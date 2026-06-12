# Energy GO — User Guide

This guide is for **operators and analysts** running Energy GO: installing it, launching the app, and using the live dashboard, 3D site view, inference sessions, and training panel. For the system specification see [`REBUILD_SPEC.md`](../REBUILD_SPEC.md); for contributing see the [developer guide](../developer_guide/index.md).

> **What Energy GO is.** A reinforcement-learning system that dispatches a grid-connected **wind + solar + battery** plant (modeled on Gansu/Jiuquan, China) to minimise total electricity cost — via time-of-use arbitrage, peak shaving, and renewable routing. The product's canonical shape is a five-stage pipeline: **config → select algorithm → train → eval → project finance**. See [`README.md`](../README.md) for the one-paragraph overview and current component status.

## Contents

| Page | What it covers |
|---|---|
| [Installation & launch](installation.md) | Install + launch with the `install_app` / `run_app` scripts, server types, accelerators, ports, env vars |
| [The dashboard](dashboard.md) | Live cost breakdown, SOC & price timelines, monthly-peak tracker, power flows, alerts |
| [The 3D site view](site_view_3d.md) | The animated turbines / PV / battery / grid scene and what its motion means |
| [Inference sessions](sessions.md) | Starting, pausing/resuming, and setting replay speed for a live policy run |
| [Training](training.md) | Launching a training job and reading the training panel (curves, throughput, checkpoints, eval) |
| [Troubleshooting](troubleshooting.md) | Ports, Python 3.11, Apple-Silicon/Rosetta, GPU detection — with the scripts' real remediation hints |

## A note on accuracy

Everything in this guide is written against what is **merged on `main`** and was exercised against the running app or the actual scripts (per the [documentation standard](../.claude/skills/docs-style/SKILL.md)). End-to-end training is now runnable from `main` — the JAX environment core (PR #33), the SAC training pipeline (PR #40), and the training/eval harness (PR #43) are all merged.
