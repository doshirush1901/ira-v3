"""Pantheon agent registry.

Import all agent classes for convenient access::

    from ira.agents import Athena, Clio, Prometheus
"""

from ira.agents.arachne import Arachne
from ira.agents.athena import Athena
from ira.agents.base_agent import BaseAgent
from ira.agents.calliope import Calliope
from ira.agents.clio import Clio
from ira.agents.delphi import Delphi
from ira.agents.hephaestus import Hephaestus
from ira.agents.hermes import Hermes
from ira.agents.iris import Iris
from ira.agents.mnemosyne import Mnemosyne
from ira.agents.nemesis import Nemesis
from ira.agents.plutus import Plutus
from ira.agents.prometheus import Prometheus
from ira.agents.sophia import Sophia
from ira.agents.sphinx import Sphinx
from ira.agents.themis import Themis
from ira.agents.tyche import Tyche
from ira.agents.vera import Vera

__all__ = [
    "BaseAgent",
    "Arachne",
    "Athena",
    "Calliope",
    "Clio",
    "Delphi",
    "Hephaestus",
    "Hermes",
    "Iris",
    "Mnemosyne",
    "Nemesis",
    "Plutus",
    "Prometheus",
    "Sophia",
    "Sphinx",
    "Themis",
    "Tyche",
    "Vera",
]
