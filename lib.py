import json
import pickle
import re
import time
from functools import lru_cache

import dnf
import networkx as nx
from tqdm import tqdm

RED_EDGE = {"color": "red"}
GREEN_EDGE = {"color": "green"}
BLUE_EDGE = {"color": "blue"}


def filter_duplicates(s):
    included = set()
    res = set()
    for pkg in s:
        if pkg.name not in included:
            included.add(pkg.name)
            res.add(pkg)
    return res


def contains_SRPM(set):
    for pkg in set:
        if pkg.sourcerpm is None:
            return True
    return False


def graph_to_sigma_JSON(g):
    d = nx.node_link_data(g, name="key")
    d["edges"] = d["links"]
    del d["links"]
    del d["directed"]
    del d["multigraph"]
    del d["graph"]
    d["attributes"] = {
        "name": "RPMGraph",
        "type": "directed",
        "multi": True,
        "allowSelfLoops": True,
    }

    return json.dumps(d)


class DNF:
    def __init__(self):
        self.base = dnf.Base()
        self.base.conf.read()
        self.base.read_all_repos()
        self.base.repos.get_matching("*").disable()
        self.base.repos.get_matching("rawhide").enable()
        self.base.repos.enable_source_repos()
        self.base.repos.enable_debug_repos()
        self.base.fill_sack(load_system_repo=False)
        self.q = self.base.sack.query().available()
        self.resolve_cache = {}
        self.stats = {
            "cache": 0,
            "file": 0,
            "file_duplicated": 0,
            "provide": 0,
            "provide_duplicated": 0,
            "name": 0,
            "markingerror": 0,
            "depsolveerror": 0,
            "transaction_provide": 0,
            "transaction_provide_duplicate": 0,
            "transaction_file": 0,
            "transaction_file_duplicate": 0,
            "transaction_provide_loop": 0,
            "transaction_file_loop": 0,
        }

    def resolve_RPM(self, string, for_pkg=None):
        if string in self.resolve_cache:
            self.stats["cache"] += 1
            return self.resolve_cache[string]

        # Provided by single package
        res = self.q.filter(provides=string, reponame="rawhide").run()
        if len(res) == 1:
            self.stats["provide"] += 1
            res = res.pop()
            self.resolve_cache[string] = res
            return res
        elif len(res) > 1:
            # Provided by multiple packages with same name
            res = filter_duplicates(res)
            if len(res) == 1:
                self.stats["provide_duplicated"] += 1
                res = res.pop()
                self.resolve_cache[string] = res
                return res

        # Exact package name
        if res := self.q.filter(name=string, reponame="rawhide").run():
            self.stats["name"] += 1
            self.resolve_cache[string] = res[0]
            return res[0]

        if string.startswith("/"):
            res = self.q.filter(file=string, reponame="rawhide").run()
            if len(res) == 1:
                self.stats["file"] += 1
                res = res.pop()
                self.resolve_cache[string] = res
                return res
            elif len(res) > 1:
                # Provided by multiple packages with same name
                res = filter_duplicates(res)
                if len(res) == 1:
                    self.stats["file_duplicated"] += 1
                    res = res.pop()
                    self.resolve_cache[string] = res
                    return res

        # Transaction resolution
        try:
            self.base.install(string)
            if for_pkg and for_pkg.sourcerpm is not None:
                self.base.package_install(for_pkg)
        except dnf.exceptions.MarkingError:
            self.base.reset(goal=True)
            self.stats["markingerror"] += 1
            return None

        try:
            self.base.resolve()
        except dnf.exceptions.DepsolveError:
            self.base.reset(goal=True)
            self.stats["depsolveerror"] += 1
            return None

        res = self.q.filter(
            provides=string, pkg=self.base.transaction.install_set
        ).run()
        if len(res) == 1:
            self.base.reset(goal=True)
            self.stats["transaction_provide"] += 1
            return res[0]
        elif len(res) > 1:
            self.base.reset(goal=True)
            self.stats["transaction_provide_duplicate"] += 1
            return res[0]

        res = self.q.filter(file=string, pkg=self.base.transaction.install_set).run()
        if len(res) == 1:
            self.base.reset(goal=True)
            self.stats["transaction_file"] += 1
            return res[0]
        elif len(res) > 1:
            self.base.reset(goal=True)
            self.stats["transaction_file_duplicate"] += 1
            return res[0]

        for p in self.base.transaction.install_set:
            if string in p.files:
                self.stats["transaction_file_loop"] += 1
                self.base.reset(goal=True)
                return p
            for pr in p.provides:
                if string == re.split(r"[ <=>]", pr.name)[0]:
                    self.base.reset(goal=True)
                    self.stats["transaction_provide_loop"] += 1
                    return p

        self.base.reset(goal=True)

        raise RuntimeError(string)

    def provides(self, pkg):
        res = set()
        for p in pkg.provides:
            provided = self.resolve_RPM(p.name)
            if provided is not None:
                res.add(provided)
        return res

    def requires(self, pkg):
        res = set()
        for p in pkg.requires:
            provider = self.resolve_RPM(p.name, for_pkg=pkg)
            if provider is None:
                continue
            if pkg.sourcerpm is None and provider.sourcerpm is None:
                raise RuntimeError(
                    f"SRPM {pkg} cannot require another SRPM {provider} via {p}"
                )
            res.add(provider)
        return filter_duplicates(res)

    def create_graph(self, with_check=False):
        start = time.time()

        self.G = nx.MultiDiGraph()

        queue = self.q.available().run()
        print(f"Packages to process: {len(queue)}")

        for i, PKG in enumerate(tqdm(queue)):
            if PKG.sourcerpm is None:
                # SRPM provides
                rpms = self.provides(PKG)

                if with_check and contains_SRPM(rpms):
                    print(
                        f"ERROR during handling {PKG} - provides contains SRPM: {rpms}"
                    )

                self.G.add_edges_from(((PKG.name, rpm.name, BLUE_EDGE) for rpm in rpms))

                # SRPM BuildRequires
                rpms = self.requires(PKG)
                if with_check and contains_SRPM(rpms):
                    print(
                        f"ERROR during handling {PKG} - build requires contains SRPM: {rpms}"
                    )

                self.G.add_edges_from(
                    ((rpm.name, PKG.name, GREEN_EDGE) for rpm in rpms)
                )
            else:
                # RPM requires
                rpms = self.requires(PKG)
                if with_check and contains_SRPM(rpms):
                    print(
                        f"ERROR during handling {PKG} - requires contains SRPM: {rpms}"
                    )

                self.G.add_edges_from(((rpm.name, PKG.name, RED_EDGE) for rpm in rpms))

            if i % 1000 == 0:
                print(len(self.resolve_cache))
                print(self.stats)

        print(f"Graph with {len(self.G.nodes)} nodes and {len(self.G.edges)} edges")
        end = time.time()
        print(f"Total seconds: {end - start}")
        print(f"Cache size: {len(self.resolve_cache)}")
        print("Stats")
        print(self.stats)
        return self.G

    def save_graph(self, filename="graph.pkl"):
        with open(filename, "wb") as f:
            pickle.dump(self.G, f)

    def load_graph(self, filename="graph.pkl"):
        with open(filename, "rb") as f:
            self.G = pickle.load(f)
        return self.G
