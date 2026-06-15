"""§2 — compute_guaranteed: the core deterministic computation."""

from .models import (
    VARIES, Effect, FactId, Graph, Node, NodeId, Registry, State, Value,
)


def varying_facts(node: Node) -> list[FactId]:
    """Return fact IDs that are VARIES at this node — DO NOT REFERENCE in content."""
    if not node.guaranteed:
        return []
    return [fid for fid, val in node.guaranteed.items() if val is VARIES]


def apply_effects(state: State, node: Node) -> State:
    """Apply a node's produces to a state, returning a new state."""
    result = dict(state)
    for eff in node.produces:
        result[eff.fact] = eff.value
    return result


def apply_choice_delta(state: State, choice) -> State:
    """Apply a choice's state_delta on top of a post-produces state."""
    if not getattr(choice, "state_delta", None):
        return state
    result = dict(state)
    for eff in choice.state_delta:
        result[eff.fact] = eff.value
    return result


def meet(s1: State, s2: State) -> State:
    """Meet two states: agree → keep value; disagree → VARIES."""
    result: State = {}
    all_keys = set(s1) | set(s2)
    for k in all_keys:
        v1 = s1.get(k, VARIES)
        v2 = s2.get(k, VARIES)
        if v1 is VARIES or v2 is VARIES or v1 != v2:
            result[k] = VARIES
        else:
            result[k] = v1
    return result


def compute_guaranteed(graph: Graph, registry: Registry) -> None:
    """Compute guaranteed state for every node in one topological pass.

    After this, node.guaranteed is set for all nodes.
    guaranteed(root) = registry initial values.
    guaranteed(N) = meet over all predecessors P of apply(guaranteed(P), P).
    """
    # Build initial state from registry
    initial_state: State = {fid: decl.initial for fid, decl in registry.items()}

    order = graph.topo_order()

    for nid in order:
        node = graph.nodes[nid]
        preds = graph.predecessors(nid)

        if not preds:
            # Root or unreachable — use initial state
            node.guaranteed = dict(initial_state)
        else:
            # Meet over all incoming EDGES (not just predecessors): two choices
            # from the same parent may carry different state_delta, and the child
            # is only guaranteed what every edge agrees on.
            incoming_states = []
            for pid in preds:
                pred_node = graph.nodes[pid]
                if pred_node.guaranteed is None:
                    continue
                post = apply_effects(pred_node.guaranteed, pred_node)
                for choice in pred_node.choices:
                    if choice.to == nid:
                        incoming_states.append(apply_choice_delta(post, choice))

            if not incoming_states:
                node.guaranteed = dict(initial_state)
            elif len(incoming_states) == 1:
                node.guaranteed = incoming_states[0]
            else:
                result = incoming_states[0]
                for s in incoming_states[1:]:
                    result = meet(result, s)
                node.guaranteed = result
