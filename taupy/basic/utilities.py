try: # Assume that CUDD is installed on the system and bindings present.
    from dd.cudd import BDD
except ModuleNotFoundError:
    from dd.autoref import BDD
    print("taupy Info: Module dd.cudd not found, reverting to dd.autoref")
from sympy.logic import to_cnf, And, Implies, Not
from sympy import symbols
import numpy as np
from random import sample, choice
from itertools import chain, combinations
from more_itertools import random_combination
import math

def dict_to_prop(dictionary):
    """
    Helper function that converts a dictionary to a propositional formula,
    acknowledging dictionary's truth-value attributions.
    """
    l = []
    for (k, v) in dictionary.items():
        if v: l.append(k)
        if not v: l.append(Not(k))
    return And(*l)

def dict_to_binary(dictionary):
    """
    A helper function that converts the dictionary representation of a position
    to its presentation in a binary string.
    """
    l = []
    for k in sorted(dictionary):
        if dictionary[k]: l.append(1)
        if not dictionary[k]: l.append(0)
    return l

def free_premises(debate):
    """
    Returns a list of premises that are "free" in the sense of [1: Def. 3].
    -----
    Referenes:
    [1] Betz, Gregor. 2009. Evaluating dialectical structures. In: Journal
        of philosophical logic 38: 283--312. DOI: 10/cxrbhh
    """
    premises = set()
    for i in debate.args:
        for j in [*i.args[0].atoms()]:
            premises.add(j)
    conclusions = {i.args[1] for i in debate.args}

    return {i for i in premises if i not in conclusions and
            Not(i) not in conclusions}

def iter_to_string(l, sep=""):
    """
    Helper function that converts a dictionary position to a bit string.
    """
    return sep.join(str(i) for i in l)

def iter_to_list_of_strings(l):
    return [str(i) for i in l]

def neighbours_of_list(l):
    """
    Find the neighbours of a position in list format. A neighbour is a position
    that has HD = 1 to the position in question.
    """
    complements = [1,0] # complements[0] == 1 and complements[1] == 0
    for i in range(len(l)):
        yield (l[:i] + [complements[l[i]]] + l[i+1:])

def satisfiability_count(formula):
    """
    Count the models that satisfy a Boolean formula, using Binary decision diagrams.
    """
    variables = iter_to_list_of_strings(formula.atoms())
    diagram = BDD()
    diagram.declare(*variables)
    expression = diagram.add_expr(str(to_cnf(formula)))
    return diagram.count(expression, nvars=len(formula.atoms()))

def satisfiability(formula, all_models = False):
    """
    Return a generator of models for the given Boolean formula, using BDDs
    """
    variables = iter_to_list_of_strings(formula.atoms())
    diagram = BDD()
    diagram.declare(*variables)

    if all_models:
        expression = diagram.add_expr(str(to_cnf(formula)))
        return [{symbols(k): v for (k, v) in m.items()} for m in \
            diagram.pick_iter(expression, care_vars={str(i) for i in \
                formula.atoms()})]
    else:
        try:
            expression = diagram.add_expr(str(to_cnf(formula)))
            next(diagram.pick_iter(expression))
            return True
        except StopIteration:
            return False

def satisfiable_neighbours(debate, position):
    """
    Return all neighbours of a (partial) position that are satisfiable
    """
    variables = list({str(i) for i in debate.atoms()} | {str(i) for i in position.keys()})
    diagram = BDD()
    diagram.declare(*variables)

    expression = diagram.add_expr(str(to_cnf(debate)))
    for m in diagram.pick_iter(expression, care_vars={str(i) for i in variables}):
        yield {symbols(k): v for (k, v) in m.items()}

def graph_from_positions(positions, return_attributions=False):
    """
    Returns a dictionary of lists (position: [neighbour1, neighbour2, ...])
    that resembles the space of the positions.

    If return_attributions is set to True, this function returns a tuple. The
    first object then is the graph representation in a dict of lists format, the
    second object is a mapping from the string representation of a position
    to its dictionary format. This is useful because non-hashable objects like
    dictionaries can not be used as identifiers of nodes in graphs.
    """
    d = {}
    props = sorted(positions[0].keys(), key=lambda x: x.sort_key())
    bits = [list (1 if p[i] else 0 for i in props) for p in positions]
    for b in bits:
        neighbourlist = [iter_to_string(x) for x in neighbours_of_list(b) if x in bits]
        d[iter_to_string(b)] = neighbourlist
    if return_attributions:
        return d, dict(zip(list(iter_to_string(b) for b in bits), positions))
    else:
        return d

def rand_index(partition1, partition2):
    """
    Calculate Rand's index, a measure of similarity for two data clusterings.
    Not yet implemented.
    """
    pass

def ari(partition1, partition2):
    """
    Calculate the Adjusted Rand Index.
    """
    # First, let's look at the number of elements
    if sum(len(l) for l in partition1) != sum(len(l) for l in partition2):
        raise ValueError("The two partitions have a different number of elements.")
    else:
        num_of_elements = sum(len(l) for l in partition1)

    contingency = contingency_matrix(partition1, partition2)
    sums_of_columns = contingency.sum(axis=0)
    sums_of_rows = contingency.sum(axis=1)

    columns = sum([n * (n-1)/2 for n in sums_of_columns])
    rows = sum([n * (n-1)/2 for n in sums_of_rows])
    elements = sum([n * (n-1)/2 for n in np.nditer(contingency)])
    expected_value = columns * rows / (num_of_elements * (num_of_elements-1)/2)

    return (elements - expected_value) / ((1/2 * (rows + columns)) - expected_value)

def contingency_matrix(partition1, partition2):
    """
    A contingency matrix, a necessary indegredient for Rand's index and the ARI.
    """
    return np.array(
        [[len(set(j) & set(k)) for j in partition1] for k in partition2]
    )

def pick_random_positions_from_debate(n, debate):
    """
    A helper function to pull `n` random positions from a debate's SCCP. Returns
    :py:obj:`False` if the debate's SCCP is smaller than `n`.
    """
    if satisfiability_count(debate) >= n:
        # Using satisfiability_count() here can spare us the construction of
        # a SCCP, which is more complex than just obtaining the SCCP's number.
        return sample(population=satisfiability(debate, all_models=True), k=n)
    else:
        return False

def subsequences_with_length(iterable, length):
    """
    A helper function to return all subsequences with a length of `length`.
    This is useful when used incrementally: rather than generating the complete
    power set, work your way up and work with what you get at every `length`.
    """
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(length+1))

def fetch_premises(pool, length, exclude=[]):
    """
    Fetch a combination of premises with length `n` from the input pool of
    sentences. This function will not return a combination of premises that
    is mentioned in `exclude`.

    This way of iteratively drawing a random sample has no natural breakpoint
    (i.e., there is no iterator that is empty at some point). Thus we estimate
    that there are at most (k over n) tries, where k is the length of the
    pool and `n` the desired length. The main weakness of this approach
    is that it can theoretically happen that the only available combination
    is not reached before the maximum amount of tries is done.
    """

    try:
        n = choice(length)
    except TypeError:
        n = length

    j = 0
    k = math.comb(len(pool), n)

    while True:
        if j < k:
            i = random_combination(pool, n)
            if i not in exclude:
                for x in i:
                    if Not(x) in i: break
                else:
                    return i
            j += 1
        else:
            return False
