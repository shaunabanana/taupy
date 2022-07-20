"""
Basic tools in simulations
"""
from sympy import symbols, Not
from random import choice, choices, sample
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import numpy as np

from taupy.analysis.polarisation import difference_matrix
from taupy.analysis.agreement import (normalised_edit_distance, 
                                      normalised_edit_agreement)
from taupy.basic.utilities import (satisfiability_count, 
                                   z3_assertion_from_argument,
                                   satisfiability)
from taupy.basic.core import EmptyDebate, Debate
from taupy.basic.positions import Position
from .update import introduce, response
from taupy.generators.maps import generate_hierarchical_argument_map
import taupy.simulation.strategies as strategies


class SimulationBase:
    """
    A super class for simulations.
    """
    def init_positions(self, positions, target_length):
        """
        Generate initial Positions. Optionally, the Positions may start off with
        explicit truth-value attributions. Positions are filled up with random
        values for truth-value attributions they do not yet have.
        """
        self.positions = []

        if target_length == None:
            target_length = len(self.sentencepool)

        for p in positions:
            if len(p) < target_length:
                # Only fill up positions that do not have the desired length.
                pool = sample(self.sentencepool, k=target_length)
                for s in pool:
                    if s not in p and len(p) < target_length:
                        # While filling up a position, catch when it reaches the
                        # desired length.
                        p[s] = choice([True, False])

        self.positions.append(positions)


class Simulation(list, SimulationBase):
    """
    A simulation in which agents introduce new arguments bit by bit. 
    For historic reasons, this kind of simulation bears the generic name.
    """

    def __init__(self,
                 directed = True,
                 debate_growth = "random",
                 events = {"introduction": 9, "new_sentence": 1},
                 sentencepool = "p:10",
                 max_sentencepool = None,
                 key_statements = None,
                 parent_debate = None,
                 argumentlength = 2,
                 positions = None,
                 copy_input_positions = True,
                 initial_position_size = None,
                 default_introduction_strategy = strategies.random,
                 default_update_strategy = "closest_coherent",
                 partial_neighbour_search_radius = 50):

        if sentencepool == "inherit": # import from parent debate
            self.sentencepool = [i for i in parent_debate.atoms()]
            raise NotImplementedError(
                "Inherited sentence pools are not implemented.")
        else:
            self.sentencepool = [i for i in symbols(sentencepool)]
            self.used_premises = []

        self.max_sentencepool = [i for i in symbols(max_sentencepool)] \
                                 if max_sentencepool else self.sentencepool
        
        if key_statements is None:
            self.key_statements = list()
        else:
            self.key_statements = [i for i in symbols(key_statements)]

        self.events = events
        self.argumentlength = argumentlength
        self.partial_neighbour_search_radius = partial_neighbour_search_radius

        if positions is not None:
            if copy_input_positions == True:
                self.init_positions(deepcopy(positions), 
                                    target_length=initial_position_size)
            else:
                self.init_positions(positions, 
                                    target_length=initial_position_size)
        else:
            self.init_positions([], target_length=0)

        if debate_growth not in ["random", "tree"]:
            raise NotImplementedError("The requested growth method is not "
                                      + "implemented. Available methods are "
                                      + "`random`  and `tree`.")
        
        self.debate_growth = debate_growth
        self.directed = directed
        self.default_introduction_strategy = default_introduction_strategy
        self.default_update_strategy = default_update_strategy
        self.log = []
        self.assertions = [] # assertions for z3.Solver and z3.Optimize
        list.__init__(self)
        # Initialise the Simulation with an empty debate. This is
        # necessary so that the initial positions can attach to some debate.
        if parent_debate == None:
            self.append(EmptyDebate())
        else:
            self.append(parent_debate)
            # Add premises in the parent debate to the used premise storage.
            for i in parent_debate.args:
                self.used_premises.append(i.args[0])

    def premise_candidates(self):
        return set(self.sentencepool + [Not(i) for i in self.sentencepool])

    def run(self, max_density=0.8, max_steps=1000, min_sccp=1, quiet=True):
        """
        Run a Simulation using ``introduction_method`` and ``update_mechanism``
        until either ``max_density`` is reached, the SCCP has an extension of
        ``min_sccp`` or ``max_steps`` have been taken.

        If ``quiet=False``, the last log entry which contains a summary of
        the simulation is not output. This is useful in batch processing of
        Simulations (see ``experiment()``).
        """

        i = 0

        while True:

            selected_event = choices([i[0] for i in self.events.items()],
                                     weights=[i[1] for i in self.events.items()])[0]

            if selected_event not in ["introduction", "new_sentence"]:
                raise NotImplementedError(
                    f"No recipe for event type {selected_event}.")

            if selected_event == "introduction":
                if self.directed and len(self.positions[-1]) >= 2:
                    # The user asked for a directed simulation and has supplied
                    # enough Positions. Now instantiate turns of trying to 
                    # introduce arguments.
                    j = 0
                    while j < len(self.positions[-1]) / 2:
                        pick_positions = sample(self.positions[-1], k=2)

                        # Support for positions with multiple introduction 
                        # strategies. First, try to pick a random element from 
                        # the list of introduction  strategies of a position. If
                        # that fails, assume that the strategy preference of a 
                        # position is not given as a list, but as a single item.
                        try:
                            pick_strategy = choice(
                                pick_positions[0].introduction_strategy)
                        except KeyError:
                            pick_strategy = pick_positions[0].introduction_strategy

                        argument_introduced = introduce(self,
                                                        source=pick_positions[0],
                                                        target=pick_positions[1],
                                                        strategy=pick_strategy)
                        if not argument_introduced:
                            # The argument introduction did not succeed in this 
                            # turn. We are trying it again if there have been 
                            # less tries than half the size of the population.
                            j += 1
                            continue
                        else:
                            # An argument was found, break out of the loop.
                            # (implies argument_introduced == True)
                            self.log.append(
                                f"Argument introduction suceeded after {j+1} attempts.")
                            break
                    else:
                        # There have been more tries equal to half of the 
                        # population size, but an argument could not be found. 
                        # This is enough grounds to terminate the simulation run.
                        self.log.append(
                            "Argument introduction did not succeed, even after "
                            + f"{j+1} attempts.")
                        argument_introduced = False

                    if argument_introduced:
                        # Check if introduction was succesful before attempting 
                        # response.
                        response(simulation=self,
                                 debate=self[-1], 
                                 positions=self.positions[-1],
                                 method=self.default_update_strategy,
                                 sentences=self.sentencepool)
                else:
                    # The user did not ask for a directed simulation and/or 
                    # provided less than 2 positions. In this case, we're 
                    # investing less work.
                    argument_introduced = introduce(
                        self, strategy=self.default_introduction_strategy)
                    if argument_introduced:
                        response(simulation=self,
                                 debate=self[-1],
                                 positions=self.positions[-1], 
                                 method=self.default_update_strategy,
                                 sentences=self.sentencepool)

                if not argument_introduced:
                    # Break out of the Simulation if no argument could be 
                    # inserted. In this case, the log will tell more about what 
                    # went wrong.
                    break

            if selected_event == "new_sentence":
                # Let's see which sentences could be inserted into the debate.
                # This will be the difference between the sentencepool and the 
                # max_sentencepool

                sentence_candidates = set(self.max_sentencepool) \
                                      - set(self.sentencepool)

                if len(sentence_candidates) > 0:
                    # Append a random candidate to the debate's sentencepool.
                    selected_sentence = choice(list(sentence_candidates))
                    self.sentencepool.append(selected_sentence)
                    self.log.append(f"Sentence {selected_sentence} added to "
                                    + "the sentence pool.")

                    # Carry along the debate stage.
                    self.append(self[-1])

                    # Now have the positions take a random stance toward the 
                    # newly inserted sentence.
                    expanded_positions = []
                    for p in self.positions[-1]:
                        e = deepcopy(p)
                        # There is a 2:1 chance that the position does not 
                        # suspend judgement on the new sentence.
                        if choice([True, True, False]):
                            # If the positions does not suspend, there is a 1:1 
                            # chance it will assign either truth value.
                            e[selected_sentence] = choice([True, False])
                        expanded_positions.append(e)

                    self.positions.append(expanded_positions)

                else:
                    # Failure to insert a sentence does not end the simulation, 
                    # but we take note of it in the log.
                    self.log.append(
                        "Tried to insert a new sentence to the debate but "
                        + "maximum extension was reached.")

            i += 1
            if self[-1].density() >= max_density or i >= max_steps or satisfiability_count(self[-1]) <= min_sccp:
                # Delete objects that can't be pickled.
                del self.assertions
                break

        self.log.append(
            "Simulation ended. "
            + str(f"{i} steps were taken. ")
            + str(f"Density at end: {self[-1].density()}. ")
            + str(f"Extension of SCCP: {satisfiability_count(self[-1])}.")
            )

        if quiet:
            return self.log[-1]
        else:
            return self

class FixedDebateSimulation(SimulationBase):
    """
    A simulation that begins with a pre-defined debate. Agents uncover arguments
    from the debate in each simulation step. The pre-defined debate follows the
    argument map generation algorithm from Betz et al. (2021).
    
    -----
    References:
    Betz, Gregor, Vera Chekan & Tamara Mchedlidze. 2021. Heuristic algorithms 
          for the approximation of mutual coherence.
    """

    def __init__(self,
                 debate_generation = {"max_density": 1.0},
                 initial_arguments = None,
                 positions = None,
                 initial_position_size = None,
                 default_update_strategy = "closest_coherent",
                 argument_selection_strategy = "any",
                 sentencepool = "p:10",
                 num_key_statements = 1,
                 partial_neighbour_search_radius = 100
                 ):

        self.log = []
        self.assertions = []
        self.partial_neighbour_search_radius = partial_neighbour_search_radius
        self.sentencepool = [i for i in symbols(sentencepool)]
        self.debate = generate_hierarchical_argument_map(
                        N = len(self.sentencepool),
                        k = int(num_key_statements),
                        **debate_generation)
        
        if positions is None:
            self.init_positions([], target_length=0)
        else:
            self.init_positions(deepcopy(positions), 
                                target_length=initial_position_size)

        self.updating_strategy = default_update_strategy
        
        if initial_arguments is None:
            self.uncovered_arguments = list()
        else:
            self.uncovered_arguments = initial_arguments

        self.argument_selection_strategy = argument_selection_strategy
        
        if self.argument_selection_strategy not in ["any", "max"]:
            raise NotImplementedError("The selected argument selection strategy "
                                      + str(self.argument_selection_strategy)
                                      + " is unknown.")

        if self.updating_strategy not in ["closest_coherent", 
                                          "closest_closed_partial_coherent"]:
            raise NotImplementedError("The selected default updating strategy "
                                      + str(self.updating_strategy)
                                      + " is unkown.")

    def __repr__(self):
        """
        Control the display of individual Simulation objects
        """
        return str(f"Simulation with {len(self.debate)} arguments, of which "
                   + f"{len(self.uncovered_arguments)} are uncovered.")

    def step(self):
        """
        Advance Simulation by one step.
        """
        # uncovering

        if len(self.positions[-1]) > 1:
            # Cache to reduce calls to enumerate()
            enum_pos = list(enumerate(self.positions[-1]))
            seen_positions = []
            argument_available = False

            while True:
                c = dict()
                available_positions = [(i, p) for (i, p) in enum_pos \
                                       if i not in seen_positions]
                if len(available_positions) == 0:
                    new_argument = False
                    break

                source_id, source = choice(available_positions)
                seen_positions.append(source_id)

                # Support for positions with multiple introduction strategies.
                # First, try to pick a random element from the list of 
                # introduction strategies of a position. If that fails, assume 
                # that the strategy preference of a position is not given as a 
                # list, but as a single item.
                try:
                    strategy = choice(source.introduction_strategy)
                except KeyError:
                    strategy = source.introduction_strategy

                for arg in [a for a in self.debate.args \
                                 if a not in self.uncovered_arguments]:

                    try:
                        reqs = arg.get_requirements()
                        premise_reqs = {k: reqs[k] for k in reqs if k in arg.args[0].atoms()}
                        conclusion_reqs = {k: reqs[k] for k in reqs if k in arg.args[1].atoms()}
                    except:
                        raise Exception(
                            "Could not retrieve requirements from argument: "
                            + f"{arg}. Arguments uncovered so far: "
                            + f"{len(self.uncovered_arguments)}")
                    
                    if strategy["pick_premises_from"] == "target":                    
                        premise_ids = [i for (i, p) in enum_pos \
                                       if premise_reqs.items() <= p.items()]                
                    
                    if strategy["pick_premises_from"] == "source":
                        premise_ids = [i for (i, p) in enum_pos \
                                       if premise_reqs.items() <= source.items()]

                    if strategy["pick_premises_from"] == None:
                        premise_ids = [i for (i, p) in enum_pos]

                    if strategy["source_accepts_conclusion"] == "Yes":
                        conclusion_source_ids = [i for (i, p) in enum_pos \
                                                 if conclusion_reqs.items() <= source.items()]

                    if strategy["source_accepts_conclusion"] == "Toleration":
                        suspend_conclusion = {k: None for k in conclusion_reqs}
                        conclusion_source_ids = [i for (i, p) in enum_pos if conclusion_reqs.items() <= source.items()] \
                                                + [i for (i, p) in enum_pos if conclusion_reqs.items() <= suspend_conclusion.items()]

                    if strategy["source_accepts_conclusion"] == "NA":
                        conclusion_source_ids = [i for (i, p) in enum_pos if i != source_id]

                    if strategy["target_accepts_conclusion"] == "No":
                        conclusion_target_ids = [i for (i, p) in enum_pos if not conclusion_reqs.items() <= p.items() and i != source_id]

                    if strategy["target_accepts_conclusion"] == "NA":
                        conclusion_target_ids = [i for (i, p) in enum_pos if i != source_id]

                    possible_targets = set(premise_ids) \
                                       & set(conclusion_source_ids) \
                                       & set (conclusion_target_ids)

                    if len(possible_targets) > 0:
                        argument_available = True
                    
                    c[arg] = len(possible_targets)

                if argument_available:
                    if self.argument_selection_strategy == "any":
                        # list of all arguments with at least one match
                        new_argument = choice([k for k in c if c[k] > 0])

                    if self.argument_selection_strategy == "max":
                        # list of all arguments that maximise the matches
                        new_argument = choice([k for k in c if c[k] == c[max(c, key=c.get)]])

                    self.log.append(
                        str(f"Agent with id {source_id} introduced {new_argument}, ")
                        + str(f"which targets {c[new_argument]} other agents.")
                    )
                    
                    break

                else:
                    self.log.append(
                        f"No {strategy} argument available for position {source}."
                    )

        else:
            new_argument = choice([i for i in self.debate.args if i not in self.uncovered_arguments])

        if new_argument:
            self.uncovered_arguments.append(new_argument)
            self.assertions.append(
                z3_assertion_from_argument(premises=new_argument.args[0].args, 
                                           conclusion=new_argument.args[1]))

            # updating
            response(simulation = self,
                     debate = Debate(*self.uncovered_arguments),
                     positions = self.positions[-1],
                     method = self.updating_strategy,
                     sentences = self.sentencepool)

            return True

        else:
            return False


    def run(self, max_density=0.8, max_steps=200, min_sccp=1, quiet=True):
        """
        Run Simulation steps until targets are reached
        """

        while True:
            if (len(self.uncovered_arguments) > max_steps 
                and satisfiability_count(Debate(*self.uncovered_arguments)) <= min_sccp) \
               or (len(self.uncovered_arguments) > 1 
                   and Debate(*self.uncovered_arguments).density() > max_density):
               break

            introduced = self.step()
            if not introduced:
                break
        
        if quiet:
            return f"Simulation ended. {len(self.uncovered_arguments)} steps taken."
        else:
            # Generate a return object that only contains pickable data.
            return {
                "positions": self.positions,
                "uncovered_arguments": self.uncovered_arguments,
                "debate": self.debate,
                "sentencepool": self.sentencepool,
                "log": self.log
            }

class SocialInfluenceSimulation(SimulationBase):
    """
    A simulation in which agents update their positions based on what
    other agents think, through a reason-exchange mechanism similar to
    Mäs & Flache (2013) or Singer et al. (2019).

    -----
    References:

    Mäs, Michael & Flache, Andreas. 2013. Differentiation without distancing:
    Explaining bi-polarization of opinions without negative influence. PLOS ONE
    8 (11). DOI: 10.1371/journal.pone.0074516.

    Singer et al. 2019. Rational social and political polarization.
    Philosophical Studies 176: 2243–2267. DOI: 10.1007/s11098-018-1124-5.
    """
    def __init__(self,
                 debate_generation = {"max_density": 0.8},
                 number_key_statements = 3,
                 sentencepool = "p:10",
                 positions = None,
                 initial_position_size = 5,
                 updating_strategy = "closest_coherent",
                 partial_neighbour_search_radius = 50,
                 influence_parameter = 0
                 ):

        self.sentencepool = [i for i in symbols(sentencepool)]
        self.key_statements = list(sentencepool)[:number_key_statements]
        self.debate = generate_hierarchical_argument_map(
                        N = len(list(self.sentencepool)),
                        k = len(self.key_statements),
                        **debate_generation)
        
        self.log = []
        self.assertions = []
        self.influence_parameter = influence_parameter
        self.partial_neighbour_search_radius = partial_neighbour_search_radius

        if positions is None:
            self.init_positions([], target_length=0)
        else:
            self.init_positions(deepcopy(positions),
                                target_length=initial_position_size)

        for p in self.positions[0]:
            p.debate = self.debate

        self.updating_strategy = updating_strategy
        # Are the initial positions closed and coherent give the debate?
        # If not, update these positions.
        # This also means that the positions in self.positions[0] will be less
        # interesting compared to those in self.positions[1]

        # Since the debate of a Social Influence Simulation never changes, we
        # need to compute the legitimate positions once. This saves a lot of 
        # computation time, but currently is only available for complete 
        # positions that do not suspend.

        if self.updating_strategy == "closest_coherent":
            self.all_models = list(satisfiability(self.debate, all_models=True))
        else:
            self.all_models = None
            self.log.append("I was unable to compute all models given the"
                            + f"updating strategy {self.updating_strategy}.")

        response(simulation = self,
                debate = self.debate,
                models = self.all_models,
                positions = self.positions[-1],
                method = self.updating_strategy,
                sentences = self.sentencepool)

    def __repr__(self):
        """
        Control the display of individual objects
        """
        return str(f"Simulation with {len(self.debate)} arguments "
                   + f"and {len(self.positions[-1])} agents.")

    def step(self):
        pick_position = choice(list(enumerate(self.positions[-1])))
        source = pick_position[1]
        source_id = pick_position[0]
        influence_item = choice(self.sentencepool)

        candidates = []

        for i, p in enumerate(self.positions[-1]):
            d = normalised_edit_distance(source, p)
            w = [1 - d*self.influence_parameter, d*self.influence_parameter]
            update = choices([True, False], weights=w)[0]
            if update:
                new_position = Position(
                    self.debate, 
                    {k: p[k] for k in p if k != influence_item},
                    introduction_strategy=p.introduction_strategy)
                if influence_item in source:
                    new_position[influence_item] = source[influence_item]

                self.log.append(
                    f"Position {i} was influenced by Position {source_id}."
                )
            else:
                new_position = p
                self.log.append(
                    f"Position {i} was not influenced by Position {source_id}."
                )

            candidates.append(new_position)

        response(simulation = self,
                 debate = self.debate,
                 positions = candidates,
                 models = self.all_models,
                 method = self.updating_strategy,
                 sentences = self.sentencepool)

    def run(self, max_steps=float("inf"), max_agreement=0.9, quiet=True):

        # The step counter
        i = 0
                
        while True:

            # Determine the current population-wide mean agreement by taking
            # the mean of the upper triangle matrix of the differences
            # between positions (assuming, for simplicity, that the difference
            # metric is symmetric.)
            current_mean_agreement = difference_matrix(
                self.positions[-1], 
                normalised_edit_agreement)[np.triu_indices(
                    len(self.positions[-1]), k=1)].mean()

            if i <= max_steps and current_mean_agreement <= max_agreement:
                self.step()
                i += 1
            else:
                break
        
        if quiet:
            return (f"Simulation ended. {i} steps taken. "
                    + f"Reached mean agreement of {current_mean_agreement}.")
        else:
            return {
                "positions": self.positions,
                "debate": self.debate,
                "sentencepool": self.sentencepool,
                "log": self.log
            }


def experiment(n, *, sim_type=Simulation, executor={}, simulations={}, runs={}):
    """
    Generate and execute `n` number of Simulations and output their results.
    The Simulations can be controlled via a dictionary passed to ``simulations``.
    The ``Simulation.run()``s can be controlled with a dictionary passed to
    ``runs``.

    Settings to the ``ProcessPoolExecutor`` should be forwarded in a dictionary
    to ``executor``.

    This function calls two Executors. The first is responsible for setting up
    the Simulations in parallel. The second performs the simulation runs. This
    is particularly helpful for Simulation types that involve substantial 
    computation for set-up, such as FixedDebateSimulation.
    """
    # TODO 1: Use logging instead of printing
    # TODO 2: Catch exceptions inside simulation processes
    print(f"Starting experiment at {time.ctime()}.")

    with ProcessPoolExecutor(**executor) as init_sim_executor:
        init_sims = [init_sim_executor.submit(sim_type, 
                                              **simulations) for _ in range(n)]
    
    simulations = [i.result() for i in init_sims]
    print(f"Simulations initialised at {time.ctime()}.")

    with ProcessPoolExecutor(**executor) as executor:
        results = [executor.submit(i.run, 
                                   quiet=False, 
                                   **runs) for i in simulations]

        for count, future in enumerate(as_completed(results), start=1):
            print(f"Simulation {count}/{n} completed at {time.ctime()}.")
    
    r = []
    for idx, i in enumerate(results):
        try:
            r.append(i.result())
        except:
            print(f"Failed to save simulation {idx}")
    return r