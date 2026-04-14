import importlib, pkgutil, time
from pathlib import Path
from .domain_base import DomainBase

START_TIME = time.time()
# Import all domain_*.py modules to register subclasses
for module_info in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if module_info.name.startswith("domain_") and module_info.name != "domain_base":
        importlib.import_module(f".{module_info.name}", __package__)

_DOMAIN_REGISTRY = {}
for cls in DomainBase.__subclasses__():
    name = cls.__name__.replace("Domain", "").lower()
    _DOMAIN_REGISTRY[name] = cls

DOMAIN_NAMES = list(_DOMAIN_REGISTRY.keys())

def get_domain(domain_name):
    if domain_name not in _DOMAIN_REGISTRY:
        raise ValueError(f"Domain {domain_name} not supported. Available: {list(_DOMAIN_REGISTRY.keys())}")
    return _DOMAIN_REGISTRY[domain_name]()

if __name__ == "__main__":
    print(f"Domains loaded in {time.time() - START_TIME:.2f} seconds")
    print(DOMAIN_NAMES)
