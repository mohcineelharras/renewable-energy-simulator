"""
LCoE Optimizer Module.

Optimizes system configuration to minimize LCoE with:
- Grid search optimization
- Genetic algorithm optimization
- Scipy minimize optimization
- Pareto front for multi-objective
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
import time
from itertools import product

from simulator.core.types import OptimizationResult


class OptimizationAlgorithm(Enum):
    """Available optimization algorithms."""
    GRID_SEARCH = "grid_search"
    RANDOM_SEARCH = "random_search"
    SCIPY_MINIMIZE = "scipy_minimize"
    GENETIC = "genetic"


@dataclass
class OptimizationVariable:
    """Variable to optimize."""
    name: str
    min_value: float
    max_value: float
    step: Optional[float] = None
    n_points: int = 5  # For grid search
    unit: str = ""
    description: str = ""
    
    def get_grid_values(self) -> List[float]:
        """Get values for grid search."""
        if self.step:
            return list(np.arange(self.min_value, self.max_value + self.step, self.step))
        return list(np.linspace(self.min_value, self.max_value, self.n_points))
    
    def get_random_value(self) -> float:
        """Get random value within bounds."""
        return np.random.uniform(self.min_value, self.max_value)


@dataclass
class OptimizationConstraint:
    """Constraint for optimization."""
    name: str
    func: Callable[[Dict[str, float]], bool]  # Returns True if satisfied
    description: str = ""


@dataclass
class OptimizationConfig:
    """Configuration for optimization run."""
    
    algorithm: OptimizationAlgorithm = OptimizationAlgorithm.GRID_SEARCH
    
    # Algorithm-specific parameters
    n_iterations: int = 100  # For random search
    population_size: int = 50  # For genetic
    generations: int = 20  # For genetic
    mutation_rate: float = 0.1
    crossover_rate: float = 0.7
    
    # Multi-objective
    multi_objective: bool = False
    objectives: List[str] = field(default_factory=lambda: ["lcoe"])
    
    # Parallel execution
    n_jobs: int = 1
    
    # Convergence
    tolerance: float = 0.01  # Stop if improvement < tolerance
    patience: int = 10  # Stop after patience iterations without improvement


class LCOEOptimizer:
    """
    LCoE optimizer for renewable energy systems.
    
    Searches for optimal configuration to minimize LCoE (or other objectives).
    
    Example:
        >>> optimizer = LCOEOptimizer(simulation_func=run_simulation)
        >>> optimizer.add_variable("pv_capacity_mw", 10, 100, step=10)
        >>> optimizer.add_variable("wind_capacity_mw", 0, 50, step=10)
        >>> optimizer.add_variable("battery_mwh", 0, 200, step=50)
        >>> result = optimizer.run(algorithm="grid_search")
        >>> print(f"Best LCOE: ${result.best_lcoe:.2f}/MWh")
    """
    
    def __init__(
        self,
        simulation_func: Callable[[Dict[str, float]], Dict[str, float]],
        config: Optional[OptimizationConfig] = None
    ):
        """
        Initialize optimizer.
        
        Args:
            simulation_func: Function that takes config dict and returns results dict
                             with at least 'lcoe' key.
            config: Optimization configuration.
        """
        self.simulation_func = simulation_func
        self.config = config or OptimizationConfig()
        self.variables: List[OptimizationVariable] = []
        self.constraints: List[OptimizationConstraint] = []
        self.results: List[Dict[str, Any]] = []
        self.best_result: Optional[Dict[str, Any]] = None
        self.convergence_history: List[float] = []
    
    def add_variable(
        self,
        name: str,
        min_value: float,
        max_value: float,
        step: Optional[float] = None,
        n_points: int = 5,
        unit: str = "",
        description: str = ""
    ) -> None:
        """Add a variable to optimize."""
        self.variables.append(OptimizationVariable(
            name=name,
            min_value=min_value,
            max_value=max_value,
            step=step,
            n_points=n_points,
            unit=unit,
            description=description,
        ))
    
    def add_constraint(
        self,
        name: str,
        func: Callable[[Dict[str, float]], bool],
        description: str = ""
    ) -> None:
        """Add a constraint to the optimization."""
        self.constraints.append(OptimizationConstraint(
            name=name,
            func=func,
            description=description,
        ))
    
    def _check_constraints(self, config: Dict[str, float]) -> bool:
        """Check if configuration satisfies all constraints."""
        for constraint in self.constraints:
            if not constraint.func(config):
                return False
        return True
    
    def _evaluate(self, config: Dict[str, float]) -> Dict[str, Any]:
        """Evaluate a single configuration."""
        result = {**config}
        
        if not self._check_constraints(config):
            result['lcoe'] = float('inf')
            result['valid'] = False
            return result
        
        try:
            sim_result = self.simulation_func(config)
            result.update(sim_result)
            result['valid'] = True
        except Exception as e:
            result['lcoe'] = float('inf')
            result['valid'] = False
            result['error'] = str(e)
        
        return result
    
    def run(
        self,
        algorithm: Optional[str] = None,
        **kwargs
    ) -> OptimizationResult:
        """
        Run optimization.
        
        Args:
            algorithm: Override algorithm from config.
            **kwargs: Additional algorithm-specific parameters.
        
        Returns:
            OptimizationResult with best configuration and all results.
        """
        if algorithm:
            self.config.algorithm = OptimizationAlgorithm(algorithm)
        
        start_time = time.time()
        self.results = []
        self.convergence_history = []
        
        if self.config.algorithm == OptimizationAlgorithm.GRID_SEARCH:
            self._run_grid_search()
        elif self.config.algorithm == OptimizationAlgorithm.RANDOM_SEARCH:
            self._run_random_search()
        elif self.config.algorithm == OptimizationAlgorithm.GENETIC:
            self._run_genetic()
        else:
            self._run_grid_search()  # Default
        
        runtime = time.time() - start_time
        
        # Find best result
        valid_results = [r for r in self.results if r.get('valid', True)]
        if valid_results:
            self.best_result = min(valid_results, key=lambda x: x.get('lcoe', float('inf')))
        else:
            self.best_result = {'lcoe': float('inf')}
        
        # Build result DataFrame
        results_df = pd.DataFrame(self.results)
        
        return OptimizationResult(
            best_config={v.name: self.best_result.get(v.name, 0) for v in self.variables},
            best_lcoe=self.best_result.get('lcoe', float('inf')),
            all_results=results_df,
            convergence=pd.Series(self.convergence_history) if self.convergence_history else None,
            runtime_seconds=runtime,
            algorithm=self.config.algorithm.value,
            n_evaluations=len(self.results),
        )
    
    def _run_grid_search(self) -> None:
        """Run grid search optimization."""
        # Generate all combinations
        grids = [v.get_grid_values() for v in self.variables]
        var_names = [v.name for v in self.variables]
        
        total_combinations = 1
        for g in grids:
            total_combinations *= len(g)
        
        best_lcoe = float('inf')
        
        for values in product(*grids):
            config = dict(zip(var_names, values))
            result = self._evaluate(config)
            self.results.append(result)
            
            if result.get('lcoe', float('inf')) < best_lcoe:
                best_lcoe = result['lcoe']
            
            self.convergence_history.append(best_lcoe)
    
    def _run_random_search(self) -> None:
        """Run random search optimization."""
        best_lcoe = float('inf')
        no_improvement_count = 0
        
        for i in range(self.config.n_iterations):
            config = {v.name: v.get_random_value() for v in self.variables}
            result = self._evaluate(config)
            self.results.append(result)
            
            lcoe = result.get('lcoe', float('inf'))
            if lcoe < best_lcoe:
                if (best_lcoe - lcoe) / best_lcoe > self.config.tolerance:
                    no_improvement_count = 0
                best_lcoe = lcoe
            else:
                no_improvement_count += 1
            
            self.convergence_history.append(best_lcoe)
            
            # Early stopping
            if no_improvement_count >= self.config.patience:
                break
    
    def _run_genetic(self) -> None:
        """Run genetic algorithm optimization."""
        pop_size = self.config.population_size
        n_vars = len(self.variables)
        
        # Initialize population
        population = []
        for _ in range(pop_size):
            individual = {v.name: v.get_random_value() for v in self.variables}
            population.append(individual)
        
        best_lcoe = float('inf')
        
        for gen in range(self.config.generations):
            # Evaluate population
            fitness = []
            for ind in population:
                result = self._evaluate(ind)
                self.results.append(result)
                lcoe = result.get('lcoe', float('inf'))
                fitness.append(1 / (lcoe + 1))  # Convert to maximization
                
                if lcoe < best_lcoe:
                    best_lcoe = lcoe
            
            self.convergence_history.append(best_lcoe)
            
            # Selection (tournament)
            new_population = []
            fitness_array = np.array(fitness)
            
            while len(new_population) < pop_size:
                # Tournament selection
                idx1, idx2 = np.random.choice(pop_size, 2, replace=False)
                parent1 = population[idx1] if fitness[idx1] > fitness[idx2] else population[idx2]
                
                idx1, idx2 = np.random.choice(pop_size, 2, replace=False)
                parent2 = population[idx1] if fitness[idx1] > fitness[idx2] else population[idx2]
                
                # Crossover
                if np.random.random() < self.config.crossover_rate:
                    child = {}
                    for v in self.variables:
                        if np.random.random() < 0.5:
                            child[v.name] = parent1[v.name]
                        else:
                            child[v.name] = parent2[v.name]
                else:
                    child = parent1.copy()
                
                # Mutation
                for v in self.variables:
                    if np.random.random() < self.config.mutation_rate:
                        child[v.name] = v.get_random_value()
                
                new_population.append(child)
            
            population = new_population
    
    def get_pareto_front(
        self,
        objective1: str = "lcoe",
        objective2: str = "capacity"
    ) -> pd.DataFrame:
        """
        Get Pareto front for two objectives.
        
        Returns configurations that are not dominated by any other.
        """
        if not self.results:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.results)
        if objective1 not in df.columns or objective2 not in df.columns:
            return df
        
        # Filter valid results
        valid = df[df.get('valid', True) == True].copy()
        
        # Find Pareto front (minimize both objectives)
        pareto = []
        for idx, row in valid.iterrows():
            dominated = False
            for _, other in valid.iterrows():
                if (other[objective1] <= row[objective1] and 
                    other[objective2] <= row[objective2] and
                    (other[objective1] < row[objective1] or other[objective2] < row[objective2])):
                    dominated = True
                    break
            if not dominated:
                pareto.append(row)
        
        return pd.DataFrame(pareto)
    
    def sensitivity_summary(self) -> pd.DataFrame:
        """Get sensitivity of LCOE to each variable."""
        if not self.results:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.results)
        
        sensitivities = []
        for v in self.variables:
            if v.name in df.columns:
                correlation = df[v.name].corr(df['lcoe'])
                sensitivities.append({
                    'variable': v.name,
                    'correlation': correlation,
                    'min': df[v.name].min(),
                    'max': df[v.name].max(),
                    'optimal': self.best_result.get(v.name) if self.best_result else None,
                })
        
        return pd.DataFrame(sensitivities)
