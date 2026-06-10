# energy_go.env — pure-JAX environment core
# Implements REBUILD_SPEC.md §3 (physics & costs) and §2 (MDP specification).
# All functions are pure: EnvState NamedTuple pytree, step() is jittable and vmappable.
