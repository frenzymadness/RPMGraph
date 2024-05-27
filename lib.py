import dnf
import networkx as nx
import time


def pkgname(name):
    return name.rsplit("-", 2)[0]


def filter_duplicates(s):
    included = set()
    res = set()
    for pkg in s:
        if pkg.name not in included:
            included.add(pkg.name)
            res.add(pkg)
    return res


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

    def find_packages(self, string):
        return self.q.filter(name=string).run()
    
    def resolve_SRPM(self, string):
        if res := self.q.filter(name=string).run():
            for pkg in res:
                if pkg.sourcerpm is None:
                    return pkg

        raise RuntimeError(f"Cannot resolve SRPM for {string}")

    def resolve(self, string):
        # Package name
        if res := self.q.filter(name=string).run():
            return res[0]

        # Provided by single package
        res = filter_duplicates(self.q.filter(provides=string).run())
        if len(res) == 1:
            return res.pop()

        # Transaction resolution
        self.base.install(string)
        self.base.resolve()
        for p in self.base.transaction.install_set:
            for pr in p.provides:
                if pr.name.startswith(string) or string in p.files:
                    self.base.reset(goal=True)
                    return p
        self.base.reset(goal=True)

        raise RuntimeError(f"Cannot resolve {string}")
    
    def SRPMs_for_RPMs(self, pkgs):
        return {self.resolve_SRPM(pkgname(p.sourcerpm)) for p in pkgs}
    
    def provides(self, pkg):
        res = set()
        for p in pkg.provides:
            res.add(self.resolve(p.name))
        return res

    def requires(self, pkg):
        res = set()
        for p in pkg.requires:
            res.add(self.resolve(p.name))
        return filter_duplicates(res)
    
    def create_graph(self, pkgname, depth=1):
        start = time.time()
        SRPM_done, RPM_done = set(), set()
        SRPM_queue, RPM_queue = set(), set()

        self.G = nx.MultiDiGraph()

        pkgs = self.find_packages(pkgname)

        for pkg in pkgs:
            if pkg.sourcerpm is None:
                SRPM_queue.add(pkg)
            else:
                RPM_queue.add(pkg)

        for round in range(depth):
            print(f"--- ROUND {round} ---")
            RPM_queue_next, SRPM_queue_next = set(), set()

            while len(SRPM_queue):
                SRPM = SRPM_queue.pop()
                SRPM_done.add(SRPM)
                print(f"SRPM - {SRPM.name}")
                rpms = self.provides(SRPM)
                for rpm in rpms:
                    print(f"{SRPM.name} provides {rpm.name}")
                    self.G.add_edge(SRPM.name, rpm.name, color="blue")
                RPM_queue_next |= (rpms - RPM_done)
                rpms = self.requires(SRPM)
                for rpm in rpms:
                    print(f"{SRPM.name} BUILD requires {rpm.name}")
                    self.G.add_edge(rpm.name, SRPM.name, color="green")
                RPM_queue_next |= (rpms - RPM_done)

            while len(RPM_queue):
                RPM = RPM_queue.pop()
                RPM_done.add(RPM)
                print(f"RPM - {RPM.name}")
                rpms = self.requires(RPM)
                for rpm in rpms:
                    print(f"{RPM.name} requires {rpm.name}")
                    self.G.add_edge(rpm.name, RPM.name, color="red")            
                RPM_queue_next |= (rpms - RPM_done)
                srpms = self.SRPMs_for_RPMs(rpms)
                SRPM_queue_next |= (srpms - SRPM_done)

            RPM_queue, SRPM_queue = RPM_queue_next, SRPM_queue_next

        print(f"Graph depth {depth} with {len(self.G.nodes)} nodes and {len(self.G.edges)} edges")
        end = time.time()
        print(f"Total seconds: {end - start}")
        return self.G
    