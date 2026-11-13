"""C4 model dataclasses with a stable JSON form (sorted, so two scans of the same tree are byte-identical)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict


@dataclass
class Component:
    id: str            # "<container>/<module>"
    name: str          # module name (dotted for Python, relative path for TS)
    container: str     # container id
    technology: str    # "Python module" | "TypeScript module"
    path: str          # file path relative to the scan root, posix separators
    externals: list[str] = field(default_factory=list)  # third-party packages this module imports


@dataclass
class Container:
    id: str
    name: str
    technology: str    # "Python package" | "npm package" | ...
    path: str          # directory relative to the scan root ("." for the root)


@dataclass
class Relation:
    src: str           # component id
    dst: str           # component id
    kind: str = "imports"


@dataclass
class Model:
    system: str
    containers: list[Container] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def normalise(self) -> "Model":
        self.containers.sort(key=lambda c: c.id)
        self.components.sort(key=lambda c: c.id)
        for c in self.components:
            c.externals = sorted(set(c.externals))
        uniq = {(r.src, r.dst, r.kind): r for r in self.relations}
        self.relations = [uniq[k] for k in sorted(uniq)]
        self.warnings = sorted(set(self.warnings))
        return self

    def component_container(self, comp_id: str) -> str | None:
        for c in self.components:
            if c.id == comp_id:
                return c.container
        return None

    def container_relations(self) -> list[tuple[str, str]]:
        """Container -> container edges derived from component relations (self-edges dropped)."""
        owner = {c.id: c.container for c in self.components}
        out = {(owner[r.src], owner[r.dst]) for r in self.relations
               if r.src in owner and r.dst in owner and owner[r.src] != owner[r.dst]}
        return sorted(out)

    def container_externals(self) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {c.id: set() for c in self.containers}
        for c in self.components:
            out.setdefault(c.container, set()).update(c.externals)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def externals(self) -> list[str]:
        return sorted({e for c in self.components for e in c.externals})

    def to_dict(self) -> dict:
        self.normalise()
        return {
            "system": self.system,
            "containers": [asdict(c) for c in self.containers],
            "components": [asdict(c) for c in self.components],
            "relations": [asdict(r) for r in self.relations],
            "container_relations": [list(p) for p in self.container_relations()],
            "externals": self.externals(),
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict) -> "Model":
        return cls(
            system=d["system"],
            containers=[Container(**c) for c in d.get("containers", [])],
            components=[Component(**c) for c in d.get("components", [])],
            relations=[Relation(**r) for r in d.get("relations", [])],
            warnings=list(d.get("warnings", [])),
        ).normalise()
