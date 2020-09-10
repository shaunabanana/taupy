from decimal import Decimal
from math import log2
from sympy.logic import (And, Implies, Not, satisfiable)
from .utilities import (iter_to_string, neighbours_of_list, 
                        satisfiability_count)

class Base():
    def graph(self):
        pass
    
    def sccp(self):
        """
        Returns a dictionary of lists (position: [neighbour1, neighbour2, ...])
        that resembles the space of coherent and complete positions. This 
        structure serves as the basis for graph analysis and graph drawing.
        
        Iteration is done over the possible neighbours of a position rather than
        with all other positions, b/c the searches' complexity will be O(n*|n|)
        where |n| is the length of a position, rather than O(n^n).
        """
        _d     = {}
        _pos   = [p for p in satisfiable(self, all_models=True)]
        _props = sorted(_pos[0].keys(), key=lambda x: x.sort_key())
        _bits  = [ list ( 1 if _p[_i] == True else 0 for _i in _props ) for _p in _pos ]
        for _b in _bits:
            _neighbourlist = [iter_to_string(x) for x in neighbours_of_list(_b) if x in _bits]
            _d[iter_to_string(_b)] = _neighbourlist
        return _d
    
    def density(self):
        _sigma = satisfiability_count ( self )
        return Decimal ( (len(self.atoms()) - log2(_sigma)) / len(self.atoms()))
    
    def list_of_premises(self):
        """
        Returns a list with tuples containing the premises used in the Debate's Arguments.
        """
        return [p.args[0].args for p in self.args]
        

class Argument(Implies,Base):
    """
    Must protect against Inputs like Argument((a,b),c)!
    """
    pass
    
class Debate(And,Base):
    """
    Debates
    """
    def __init__(self, *args): # Check *args
        And.__init__(self)
        self.actual_positions = []
